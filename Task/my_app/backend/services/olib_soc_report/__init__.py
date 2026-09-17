"""OLIB SOC VMAX 例行报表（直连 VMAX 数仓 GBase 8a 取数）。

入口：`olib_soc_report_service.run_olib_soc_report()`（任务注册见 backend/task_registry.py，
task_id=olib_soc_vmax_report）；模块 docstring 里有 9 个报表块与表分区说明。

这里用惰性再导出（PEP 562），避免 `python -m ...olib_soc_report_service` 时先导入包又执行模块
产生 runpy 警告，也避免无关代码路径上的重依赖导入。
"""
__all__ = ["BLOCKS", "SHEET_ORDER", "load_config", "resolve_window", "run_olib_soc_report"]


def __getattr__(name):
    if name in __all__:
        from backend.services.olib_soc_report import olib_soc_report_service as _svc
        return getattr(_svc, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def __dir__():
    return sorted(__all__)
