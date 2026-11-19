DRAFT = {"type": "string", "description": "draft folder name, see capcut.list"}
PLACE = {  # shared by capcut.add, capcut.text and capcut.edit action=set
    "scale": {"type": "number", "exclusiveMinimum": 0},
    "pos_x": {"type": "number", "description": "-1..1 is left..right edge of the canvas"},
    "pos_y": {"type": "number", "description": "-1..1 is bottom..top edge of the canvas"},
    "rotation": {"type": "number", "description": "degrees"},
    "opacity": {"type": "number", "minimum": 0, "maximum": 1},
}
