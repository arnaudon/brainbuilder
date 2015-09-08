'''algorithm to clip a cell density distributions'''
import h5py
import numpy as np
from brainbuilder.utils import genbrain as gb


def select_region(annotation_raw, density_raw, hierarchy, region_name, inverse=False):
    '''Trim a density voxel dataset to keep only those that belong to a desired region
    or the opposite. Returns a copy where regions of no interest have been clipped out.

    Args:
        annotation_raw: voxel data from Allen Brain Institute (can be crossrefrenced with hierarchy)
        density_raw: voxel data from Allen Brain Institute.
            Called "atlasVolume" in their website.
            Each voxel represents a value that once normalised, can be treated as a probability
            of cells appearing in this voxel.
        hierarchy: json from Allen Brain Institute
        region_name: the name of the region of interest (can be crossrefrenced with hierarchy)
        inverse(bool): Invert the selection, so that everything *BUT* the region is selected

    Returns:
        density: exactly same format as input, but the values outside the region of interest has
        been set to 0
    '''
    in_region = gb.get_regions_mask_by_names(annotation_raw, hierarchy, [region_name])
    if inverse:
        in_region = np.negative(in_region)
    return density_raw * in_region


def select_hemisphere(density_raw, left=True):
    '''Trim a density voxel dataset to keep only those in one of the two hemispheres.

    Args:
        density_raw: voxel data from Allen Brain Institute.
        left: if True select the left hemisphere (default), otherwise select the right one.
    '''
    in_region = np.ones_like(density_raw, dtype=np.bool)
    in_region[:, :, in_region.shape[2] / 2:] = False
    if not left:
        in_region = np.negative(in_region)
    return density_raw * in_region


def serialize_region(dst_file, region):
    '''Serialize region

    Args:
        dst_file(str): fullpath to filename to write
        region: np.array
    '''
    with h5py.File(dst_file, 'w') as h5:
        h5.create_dataset('region', data=region)


def deserialize_region(src_file):
    '''De-serialize orientation fields

    Args:
        src_file(str): fullpath to filename to write

    Returns:
        region information as np.array
    '''
    with h5py.File(src_file, 'r') as h5:
        return np.array(h5['region'])
