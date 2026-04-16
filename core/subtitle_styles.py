import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class SubtitleStyle:
    name: str
    fontname: str
    fontsize: int
    primary_color: str
    outline_color: str
    back_color: str
    bold: int
    outline: int
    shadow: int
    alignment: int
    margin_v: int
    
    # Word-level effect settings
    active_color: str
    hook_color: str
    active_scale: float = 1.0  # e.g., 1.1 for 110%
    hook_scale: float = 1.05
    
    def generate_ass_style_header(self) -> str:
        # Standard format string for ASS styles
        # Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
        return (
            f"Style: {self.name},{self.fontname},{self.fontsize},{self.primary_color},"
            f"&H0000D7FF,{self.outline_color},{self.back_color},"
            f"{self.bold},0,0,0,100,100,0,0,1,{self.outline},{self.shadow},"
            f"{self.alignment},80,80,{self.margin_v},1\n"
        )


STYLES = {
    "hormozi": SubtitleStyle(
        name="Hormozi",
        fontname="Arial Black",
        fontsize=92,
        primary_color="&H00FFFFFF",
        outline_color="&H00000000",
        back_color="&H80000000",
        bold=-1, # True
        outline=5,
        shadow=3,
        alignment=2, # Bottom Center
        margin_v=140,
        active_color="&H00FFFFFF",
        hook_color="&H0000FFFF", # Yellow in ASS (AABBGGRR)
        active_scale=1.1,
        hook_scale=1.15
    ),
    "mrbeast": SubtitleStyle(
        name="MrBeast",
        fontname="Impact",
        fontsize=110,
        primary_color="&H00FFFFFF",
        outline_color="&H00000000",
        back_color="&H00000000", # No background box
        bold=-1,
        outline=8,
        shadow=0,
        alignment=2,
        margin_v=160,
        active_color="&H00FFFFFF",
        hook_color="&H0000FF00", # Green
        active_scale=1.2,
        hook_scale=1.25
    ),
    "minimalist": SubtitleStyle(
        name="Minimalist",
        fontname="Arial",
        fontsize=70,
        primary_color="&H00E0E0E0", # Light gray inactive
        outline_color="&H00000000",
        back_color="&H00000000",
        bold=0,
        outline=2,
        shadow=1,
        alignment=2,
        margin_v=100,
        active_color="&H00FFFFFF", # Bright white active
        hook_color="&H00FFFFFF",
        active_scale=1.0,
        hook_scale=1.05
    )
}

def get_style(style_name: str) -> SubtitleStyle:
    """Returns the SubtitleStyle configuration for the given name."""
    name = style_name.lower().strip()
    return STYLES.get(name, STYLES["hormozi"])
