import os
import warnings
from collections import namedtuple
from pathlib import Path
from typing import Union

import pandas as pd
from tables import NaturalNameWarning, PerformanceWarning

from src.run import get_trace
from src.constants import (AIS_LABEL, DISTANCE_LABEL, SECTION_LABEL,
                           SITE_LABEL, SOMA_LABEL, TERMINAL_LABEL, TIME_LABEL,
                           VOLTAGE_LABEL)

APCount = namedtuple("APCount", "n")

_cache_root = ".cache"


def set_cache_root(root):
    global _cache_root
    _cache_root = root


def get_cache_root():
    global _cache_root
    return _cache_root


def get_file_path(name: Union[str, Path], root=None, ext=".h5"):
    """From a base name, get the Path object that specifies the 'ext' file in the '.cache' directory."""
    if root is None:
        root = get_cache_root()

    root_dir = Path(root)
    if not ext.startswith("."):
        ext = "." + ext
    path = Path(str(name).replace(ext, "") + ext)

    if root_dir not in path.parents:
        path = root_dir / path
    if not path.parent.exists():
        path.parent.mkdir()

    return path


def _ap_series_to_ap(ap_series):
    return {key: APCount(val)
            if isinstance(val, float)
            else [APCount(v) for v in val]
            for key, val in ap_series.items()
            }


def get_cached_df(name, *args, **kwargs):
    """Like `get_trace` but saves a copy.

    Internally, calls `get_trace` if it cannot find a local cached version according to `name` in the `cache_root`.
    """
    cache_root = kwargs.pop("cache_root", None)

    path = get_file_path(name, root=cache_root)
    is_test = "test" in name

    if not is_test and path.exists():
        try:
            x_df = pd.read_hdf(path, "df")
        except KeyError:
            x_df = None
        ap_series = pd.read_hdf(path, "apn")
        AP = _ap_series_to_ap(ap_series)
        return AP, x_df

    t, v, AP, x_df = get_trace(*args, **kwargs)

    if x_df is not None and not is_test:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=NaturalNameWarning)
            x_df.to_hdf(path, f"/df", "w", complevel=7)

    apn = {}
    if isinstance(AP, dict):
        for key, val in AP.items():
            if isinstance(val, list):
                apn[key] = tuple([sub_val.n for sub_val in val])
            else:
                apn[key] = val.n
    else:
        apn["soma"] = AP.n

    # copy hoc data to a pandas Series
    ap_series = pd.Series(apn)
    AP = _ap_series_to_ap(ap_series)

    if not is_test:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=Warning)
            ap_series.to_hdf(path, f"/apn", complevel=7)

    return AP, x_df


def wide_to_long(df):
    _x = df.reset_index(drop=False)
    new_df = _x.melt(id_vars=[TIME_LABEL], var_name=df.columns.names,
                     value_name=VOLTAGE_LABEL).convert_dtypes()
    return new_df


def is_long_form(df):
    return isinstance(df, pd.DataFrame) and TIME_LABEL in df.columns


def concise_df(long_df, soma=False):
    assert is_long_form(long_df), "expected dataframe to be in long form"

    section_map = {"axon[1]": AIS_LABEL}

    if soma:
        soma_mask = long_df[DISTANCE_LABEL] == 0
    else:
        soma_mask = long_df[DISTANCE_LABEL] < 0
    axon_mask = long_df[DISTANCE_LABEL] == long_df[
        long_df[SECTION_LABEL] == "axon[1]"
    ][DISTANCE_LABEL].max()
    node_mask = long_df[DISTANCE_LABEL] == long_df[DISTANCE_LABEL].max()
    mask_long_df = long_df[(soma_mask | axon_mask | node_mask)]

    ser = mask_long_df[SECTION_LABEL].map(
        lambda x: section_map.get(x, TERMINAL_LABEL))

    ser.name = SITE_LABEL

    return pd.concat([mask_long_df, ser], axis=1)


if __name__ == "__main__":
    import numpy as np
    try:
        from pv_nrn import get_pv
    except ImportError:
        print("must be run from `pv-scn1a` directory")
    pv = get_pv()
    amp = 0.1
    dur = 10
    test_name = "test"
    test_path = Path(".cache") / f"{test_name}.h5"

    if test_path.exists():
        os.remove(test_path)
        assert not test_path.exists()

    AP, _df = get_cached_df("test", pv, amp, dur, shape_plot=True)
    assert test_path.exists()

    AP, loaded_df = get_cached_df(test_path)
    assert np.all(loaded_df == _df), "values weren't stored/loaded properly!"
