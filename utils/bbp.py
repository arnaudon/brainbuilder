'''compatibility functions with existing BBP formats'''
import numpy as np
import pandas as pd
import itertools
from lxml import etree
from brainbuilder.utils import genbrain as gb
from brainbuilder.utils import traits as tt
from scipy.ndimage import distance_transform_edt  # pylint: disable=E0611


import logging
L = logging.getLogger(__name__)


def map_regions_to_layers(hierarchy, region_name):
    '''map regions in the hierarchy to the layer divisions used in BBP

    Returns:
        A dictionary where the key is the region id according to the Allen Brain data and
        the value is a tuple of the integer indices of the 6 layers used in BBP: 1, 2, 3, 4, 5, 6
    '''

    sub_area_names = gb.collect_in_hierarchy(hierarchy, 'name', region_name, 'name')

    layer_mapping = {
        'layer 1': (1,),
        'layer 2/3': (2, 3),
        'layer 2': (2, ),
        'layer 3': (3, ),
        'layer 4/5': (4, 5),
        'layer 4': (4,),
        'layer 5/6': (5, 6),
        'layer 5': (5,),
        'layer 6': (6,),
        'layer 6a': (6,),
        'layer 6b': (6,),
        ', 6a': (6,),
        ', 6b': (6,),
    }
    layer_groups = {}
    for subarea in sub_area_names:
        for name, indices in layer_mapping.items():
            if subarea.lower().endswith(name):
                area = gb.find_in_hierarchy(hierarchy, 'name', subarea)
                layer_groups[area[0]['id']] = indices

    return layer_groups


def load_recipe(recipe_filename):
    '''take a BBP builder recipe and return the probability distributions for each type

    Returns:
        A DataFrame with one row for each posibility and columns:
            layer, mtype, etype, mClass, sClass, percentage
    '''
    recipe_tree = etree.parse(recipe_filename)

    sclass_alias = {
        'INH': 'inhibitory',
        'EXC': 'excitatory'
    }

    def read_records():
        '''parse each neuron posibility in the recipe'''

        for layer in recipe_tree.findall('NeuronTypes')[0].getchildren():

            for structural_type in layer.getchildren():
                if structural_type.tag == 'StructuralType':

                    for electro_type in structural_type.getchildren():
                        if electro_type.tag == 'ElectroType':

                            percentage = (float(structural_type.attrib['percentage']) / 100 *
                                          float(electro_type.attrib['percentage']) / 100)

                            yield [
                                int(layer.attrib['id']),
                                structural_type.attrib['id'],
                                electro_type.attrib['id'],
                                structural_type.attrib['mClass'],
                                sclass_alias[structural_type.attrib['sClass']],
                                percentage
                            ]

    return pd.DataFrame(read_records(), columns=['layer',
                                                 'mtype', 'etype',
                                                 'mClass', 'sClass',
                                                 'percentage'])


def transform_recipe_into_spatial_distribution(annotation_raw, recipe, region_layers_map):
    '''take distributions grouped by layer ids and a map from regions to layers
    and build a volumetric dataset that contains the same distributions

    Returns:
        A SpatialDistribution object where the properties of the traits_collection are:
        mtype, etype, mClass, sClass
    '''
    distributions = pd.DataFrame(data=0.0,
                                 index=recipe.index,
                                 columns=region_layers_map.keys())

    for region_id, layer_ids in region_layers_map.items():
        for layer_id in layer_ids:
            data = recipe[recipe.layer == layer_id]['percentage']
            distributions.loc[data.index, region_id] = data.values

    distributions = tt.normalize_distribution_collection(distributions)

    return tt.SpatialDistribution(annotation_raw, distributions, recipe)


def load_recipe_as_spatial_distribution(recipe_filename, annotation_raw, hierarchy, region_name):
    '''load the bbp recipe and return a spatial voxel-based distribution

    Returns:
        see transform_into_spatial_distribution
    '''
    region_layers_map = map_regions_to_layers(hierarchy, region_name)

    recipe = load_recipe(recipe_filename)

    return transform_recipe_into_spatial_distribution(annotation_raw,
                                                      recipe,
                                                      region_layers_map)


def load_neurondb_v4(neurondb_filename):
    '''load a neurondb v4 file

    Returns:
        A DataFrame where the columns are:
            morphology, layer, mtype, etype, metype, placement_hints
    '''

    def read_records(lines):
        '''parse each record in a neurondb file'''
        for line in lines:
            if not line.strip():
                continue
            fields = line.split()
            morphology, layer, mtype, etype, _ = fields[:5]
            placement_hints = list(float(h) for h in fields[5:])
            # skipping metype because it's just a combination of the mtype and etype values
            yield [morphology, int(layer), mtype, etype, placement_hints]

    with open(neurondb_filename) as f:
        return pd.DataFrame(read_records(f.readlines()),
                            columns=['morphology', 'layer', 'mtype', 'etype', 'placement_hints'])


def get_morphologies_by_layer(neurondb):
    '''group morphologies by layer

    Args:
        neurondb: A DataFrame with the contents of a neurondbv4.dat (see load_neurondb_4).

    Returns:
        A dictionary where the keys are layer ids and the values lists of morphologies
    '''
    return dict((l, list(ns)) for l, ns in itertools.groupby(neurondb, lambda m: m['layer']))


def get_morphologies_by_layer_group(morphs_by_layer, layer_ids):
    '''group morphologies by layer group of layers

    Args:
        morphs_by_layer: dictionary where the keys are layer ids and the values are
            lists of morphologies
        layer_ids: a collection of layer ids

    Returns:
        A list of all of the available morphologies for a group of layers
    '''
    return list(itertools.chain(*(morphs_by_layer[layer_id] for layer_id in layer_ids)))


def get_placement_hints_table(morphs):
    '''collect the placement hint scores for a group of morphologies.

    Placement hints are a series of numbers associated with each morphology. This numbers
    represent how good a fit a morphology is to each subsection of space after this has been
    evenly splitted.

    For example, having a morphology with scores [1, 2, 1] means that it is more likely to
    find this morphology in the second third of a space than it is to find it in the first or
    the last thirds.

    The original concept of "space" was layers and they were divided in the Y direction
    (towards pia). This allowed, for example, having morphologies appear only in the bottom
    half of a layer. Now that we are dealing with complex volumes, bottom and top don't mean
    much. Here "space" is just a collection of voxels which can be grouped according to some
    metric (distance to exterior).

    Note that this metric is applied to the voxel bins in reverse order because the placement
    hints are sorted bottom to top which means biggest distance to smallest distance.

    See BlueBuilder function:TinterfaceLayer::createMicrocircuitColumn
    in Objects/interfaceLayer.cxx: 717

    Args:
        morphs: a collection of morphologies.

    Returns:
        A DataFrame array that contains the placement hint scores for the given morphologies.
        This table has one row for each morphology and one column for each region subdivision
    '''
    subdivision_count = gb.lcmm(morphs.placement_hints.map(len).as_matrix())

    region_dist_table = pd.DataFrame(dtype=np.float,
                                     index=morphs.index,
                                     columns=np.arange(subdivision_count))

    groups = morphs.placement_hints.groupby(lambda k: len(morphs.placement_hints[k]))
    for length, hints_group in groups:

        # TODO find a nicer way to get a 2D array from an array of lists
        count = len(hints_group)
        scores = np.array(list(itertools.chain(*hints_group.values))).reshape((count, length))

        # placement hints are organised bottom (high score) to top (low score)
        scores = np.fliplr(scores)

        repetitions = [subdivision_count // length] * length
        extended = np.repeat(scores, repetitions, axis=1)

        region_dist_table.ix[hints_group.index] = extended

    return region_dist_table


def reverse_region_layers_map(region_layers_map):
    ''' reverse the mapping between layers and regions

    Args:
        region_layers_map: a dict where the keys are region ids and the values tuples of layer ids

    Returns:
        A dict where the keys are tuples of layer ids and the keys lists of region ids'''
    inv_map = {}
    for k, v in region_layers_map.iteritems():
        inv_map[v] = inv_map.get(v, [])
        inv_map[v].append(k)

    return inv_map


def get_region_distributions_from_placement_hints(neurondb, region_layers_map):
    '''for every region, return the list of probability distributions for each potential
    morphology. The probabilites are taken from the placement hint scores.
    There is one distribution for each subdivision of the region and they are sorted
    the same way as the placement hint scores are: from furthest to pia to closest to pia

    Returns:
        A dict where each key is a tuple of region ids and the value a distribution collection.
    '''

    regions_dists = {}
    for layer_ids, region_ids in reverse_region_layers_map(region_layers_map).iteritems():

        region_morphs = neurondb[np.in1d(neurondb.layer, layer_ids)]

        dists = get_placement_hints_table(region_morphs)

        regions_dists[tuple(region_ids)] = tt.normalize_distribution_collection(dists)

    return regions_dists


def assign_distributions_to_voxels(voxel_scores, bins):
    '''group voxels by a their score, and assign a distribution to each group.
    There will be as many groups as distributions. The distributions are assigned in order
    to the groups from the lowest scores to the higher scores

    Returns:
        An array of the same shape as voxel_scores, where each value is an index
        in the interval [0, bins)
    '''
    count_per_bin, _ = np.histogram(voxel_scores, bins=max(bins, 1))
    voxel_indices = np.argsort(voxel_scores)

    region_dist_idxs = np.ones(shape=voxel_scores.shape, dtype=np.int) * -1

    idx = 0
    for dist_idx, bin_count in enumerate(count_per_bin):
        indices = voxel_indices[idx: idx + bin_count]
        region_dist_idxs[indices] = dist_idx
        idx += bin_count

    return region_dist_idxs


def transform_neurondb_into_spatial_distribution(annotation_raw, neurondb, region_layers_map):
    '''take the raw data from a neuron db (list of dicts) and build a volumetric dataset
    that contains the distributions of possible morphologies.

    In the context of layers, the bins for the placement hint are numbered from the bottom of
    the layer (further from pia) towards the top (closer to pia)

    Args:
        annotation_raw: voxel data from Allen Brain Institute to identify regions of space.
        neurondb: list of dicts containing the information extracted from a neurondb v4 file.
            only the 'layer' attribute is strictly needed
        region_layers_map: dict that contains the relationship between regions (referenced by
            the annotation) and layers (referenced by the neurondb). The keys are region ids
            and the values are tuples of layer ids.

    Returns:
        A SpatialDistribution object where the properties of the traits_collection are those
        obtained from the neurondb.
    '''

    # "outside" is tagged in the annotation_raw with 0
    # This will calculate, for every voxel, the euclidean distance to
    # the nearest voxel tagged as "outside" the brain
    distance_to_pia = distance_transform_edt(annotation_raw)
    distance_to_pia = distance_to_pia.flatten()

    # TODO take only the top 8% for each mtype-etype combination
    region_dists = get_region_distributions_from_placement_hints(neurondb, region_layers_map)

    flat_field = np.ones(shape=np.product(annotation_raw.shape), dtype=np.int) * -1

    all_dists = pd.DataFrame()

    for region_ids, dists in region_dists.iteritems():
        flat_mask = np.in1d(annotation_raw, region_ids)

        voxel_distances = distance_to_pia[flat_mask]
        voxel_dist_indices = assign_distributions_to_voxels(voxel_distances, len(dists.columns))

        offset = len(all_dists.columns)
        dists.columns += offset
        flat_field[flat_mask] = voxel_dist_indices + offset
        all_dists = pd.concat([all_dists, dists], axis=1)

    return tt.SpatialDistribution(flat_field.reshape(annotation_raw.shape),
                                  all_dists.fillna(0.0),
                                  neurondb)


def load_neurondb_v4_as_spatial_distribution(neurondb_filename,
                                             annotation_raw, hierarchy, region_name):
    '''load the bbp recipe and return a spatial voxel-based distribution

    Returns:
        see transform_into_spatial_distribution
    '''
    region_layers_map = map_regions_to_layers(hierarchy, region_name)

    neurondb = load_neurondb_v4(neurondb_filename)

    return transform_neurondb_into_spatial_distribution(annotation_raw,
                                                        neurondb,
                                                        region_layers_map)
