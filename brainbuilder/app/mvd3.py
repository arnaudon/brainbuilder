""" Tools for working with MVD3 """

from builtins import input  # pylint: disable=redefined-builtin

import shutil

import click
import numpy as np
import pandas as pd

from voxcell import CellCollection, VoxelData
from brainbuilder.utils import bbp


@click.group()
def app():
    """ Tools for working with MVD3 """
    pass


@app.command()
@click.argument("mvd3")
@click.option("--recipe", help="Path to builder recipe XML", required=True)
@click.option("-o", "--output", help="Path to output MVD3", required=True)
def reorder_mtypes(mvd3, recipe, output):
    """ Align /library/mtypes with builder recipe """
    tmp_path = output + "~"
    shutil.copy(mvd3, tmp_path)
    bbp.reorder_mtypes(tmp_path, recipe)
    shutil.move(tmp_path, output)


@app.command()
@click.argument("mvd3")
@click.option("-p", "--prop", help="Property name to use", required=True)
@click.option("-d", "--voxel-data", help="Path NRRD with to volumetric data", required=True)
@click.option("-o", "--output", help="Path to output MVD3", required=True)
def add_property(mvd3, prop, voxel_data, output):
    """ Add property to MVD3 based on volumetric data """
    cells = CellCollection.load_mvd3(mvd3)
    if prop in cells.properties:
        choice = input(
            "There is already '%s' property in the provided MVD3. Overwrite (y/n)? " % prop
        )
        if choice.lower() not in ('y', 'yes'):
            return
    voxel_data = VoxelData.load_nrrd(voxel_data)
    cells.properties[prop] = voxel_data.lookup(cells.positions)
    cells.save_mvd3(output)


@app.command()
@click.argument("mvd3")
@click.option("--seeds", help="Comma-separated circuit seeds (4 floats)", required=True)
@click.option("-o", "--output", help="Path to output MVD3", required=True)
def set_seeds(mvd3, seeds, output):
    """ Set /circuit/seeds """
    seeds = [float(x) for x in seeds.split(",")]
    assert len(seeds) == 4
    mvd3 = CellCollection.load_mvd3(mvd3)
    mvd3.seeds = np.array(seeds, dtype=np.float64)
    mvd3.save_mvd3(output)


@app.command()
@click.argument("mvd3")
@click.option("--morph-dir", help="Path to morphology folder", required=True)
@click.option("-o", "--output", help="Path to output MVD2", required=True)
def to_mvd2(mvd3, morph_dir, output):
    """ Convert to MVD2 """
    cells = CellCollection.load_mvd3(mvd3)
    bbp.save_mvd2(output, morph_dir, cells)


@app.command()
@click.argument("mvd3")
@click.option("--mecombo-info", help="Path to TSV file with ME-combo table", default=None)
@click.option("--population", help="Population name", default="default", show_default=True)
@click.option("-o", "--output", help="Path to output HDF5", required=True)
def to_sonata(mvd3, mecombo_info, population, output):
    """ Convert to SONATA """
    from brainbuilder.utils.sonata import write_nodes_from_mvd3
    write_nodes_from_mvd3(
        mvd3_path=mvd3,
        mecombo_info_path=mecombo_info,
        out_h5_path=output,
        population=population
    )


@app.command()
@click.argument("mvd3", nargs=-1)
@click.option("-o", "--output", help="Path to output MVD3", required=True)
def merge(mvd3, output):
    """ Merge multiple MVD3 files """
    chunks = [CellCollection.load_mvd3(filepath).as_dataframe() for filepath in mvd3]
    merged = pd.concat(chunks, ignore_index=True)
    merged.index = 1 + np.arange(len(merged))
    CellCollection.from_dataframe(merged).save_mvd3(output)
