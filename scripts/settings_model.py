"""Limbic Depth Map Renderer — Settings Model.
============================================
Single source of truth for all depth map settings.
Replaces DEFAULT_SETTINGS, _PARM_MAP, PARM_DEFS, _collect(), _load_ui() duplication.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


def _menu_for(field_name: str) -> list[str] | None:
    return _MENU_ITEMS.get(field_name)


def _parm_label(field_name: str) -> str:
    return _PARM_LABELS.get(field_name, field_name.replace("_", " ").title())


@dataclass
class DepthMapSettings:
    use_custom_range: bool = False
    near: float = 0.1
    far: float = 1000.0
    normalization: str = "LINEAR"
    scale_factor: float = 1.0
    invert: bool = True
    contrast: float = 0.2
    brightness: float = 0.0
    clip_enable: bool = False
    near_clip: float = 0.01
    far_clip: float = 100.0
    exposure: float = 0.0
    gamma: float = 1.0
    black_point: float = 0.0
    white_point: float = 1.0
    output_path: str = ""
    format: str = "PNG"
    bit_depth: str = "16"
    preview: bool = False
    animation: bool = False
    use_scene_range: bool = True
    frame_start: int = 1
    frame_end: int = 250
    mask_enabled: bool = False
    mask_source: str = "OBJECT_INDEX"
    mask_index: int = 1
    mask_format: str = "GRAYSCALE"
    mask_output_path: str = ""
    setup_complete: bool = False
    mask_setup_complete: bool = False

    def validate(self):
        if self.use_custom_range and self.near >= self.far:
            raise ValueError(
                f"far ({self.far}) must be > near ({self.near})")
        if self.scale_factor == 0.0:
            raise ValueError("scale_factor cannot be zero")
        if self.clip_enable and self.near_clip >= self.far_clip:
            raise ValueError(
                f"far_clip ({self.far_clip}) must be > near_clip ({self.near_clip})")
        if self.gamma <= 0.0:
            raise ValueError("gamma must be > 0")
        if not (0.0 <= self.black_point < self.white_point <= 1.0):
            raise ValueError(
                "black_point must be in [0,1), white_point in (0,1], "
                "and black_point < white_point")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DepthMapSettings:
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


_PARM_LABELS = {
    "use_custom_range": "Custom Near/Far Range",
    "near":             "Near",
    "far":              "Far",
    "normalization":    "Normalization",
    "scale_factor":     "Scale Factor",
    "invert":           "Invert",
    "brightness":       "Brightness",
    "contrast":         "Contrast",
    "output_path":      "Output Path",
    "format":           "Format",
    "bit_depth":        "Bit Depth",
    "preview":          "Preview",
    "animation":        "Animation",
    "use_scene_range":  "Use Scene Range",
    "frame_start":      "Frame Start",
    "frame_end":        "Frame End",
    "mask_enabled":     "Mask Enabled",
    "mask_source":      "Mask Source",
    "mask_index":       "Object Index",
    "mask_format":      "Mask Format",
    "mask_output_path": "Mask Output Path",
}

_MENU_ITEMS = {
    "normalization": ["LINEAR", "LOGARITHMIC", "RAW"],
    "format":        ["PNG", "TIFF", "EXR"],
    "bit_depth":     ["8", "16"],
    "mask_source":   ["OBJECT_INDEX", "CRYPTOMATTE"],
    "mask_format":   ["GRAYSCALE", "RGBA"],
}

_INTERNAL_FIELDS = {"setup_complete", "mask_setup_complete"}

_PARM_NAME_MAP = {
    "use_custom_range": "usecustomrange",
    "scale_factor":     "scalefactor",
    "use_scene_range":  "usescenerange",
    "mask_enabled":     "maskenabled",
    "mask_source":      "masksource",
    "mask_index":       "maskindex",
    "mask_format":      "maskformat",
    "mask_output_path": "maskoutputpath",
    "output_path":      "outputpath",
    "bit_depth":        "bitdepth",
    "frame_start":      "framestart",
    "frame_end":        "frameend",
}


def parm_name(field_name: str) -> str:
    return _PARM_NAME_MAP.get(field_name, field_name)


_TYPE_MAP = {
    "bool": "toggle",
    "float": "float",
    "int": "int",
    "str": "string",
}


def _python_type_to_parm(python_type) -> str:
    if isinstance(python_type, type):
        if python_type is bool:
            return "toggle"
        if python_type is float:
            return "float"
        if python_type is int:
            return "int"
    if isinstance(python_type, str):
        return _TYPE_MAP.get(python_type, "string")
    return "string"


def _default_str(f) -> str:
    val = f.default
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    return str(val)


def generate_parm_defs() -> list[tuple]:
    result = []
    for f in fields(DepthMapSettings):
        if f.name in _INTERNAL_FIELDS:
            continue
        pname = parm_name(f.name)
        label = _parm_label(f.name)
        ptype = _python_type_to_parm(f.type)
        default = _default_str(f)
        menu = _menu_for(f.name)
        result.append((pname, label, ptype, default, menu))
    return result


def generate_parm_map() -> dict[str, str]:
    result = {}
    for f in fields(DepthMapSettings):
        if f.name in _INTERNAL_FIELDS:
            continue
        result[parm_name(f.name)] = f.name
    return result


def generate_default_settings() -> dict:
    return {f.name: f.default for f in fields(DepthMapSettings)}
