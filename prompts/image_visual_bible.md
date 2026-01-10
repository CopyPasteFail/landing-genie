You are creating a visual bible for consistent product imagery.

- Product description: {{ product_prompt }}
- User clarifications for visuals:
{{ image_follow_up_context }}

Return a JSON object only. Use concise, production-ready values for each field.
Include these fields at minimum (add more if helpful):
- color_palette
- primary_material
- secondary_materials
- finish_texture
- logo_placement
- proportions_scale
- distinctive_features
- lighting_style
- background_style

Output JSON only with no markdown fences.
