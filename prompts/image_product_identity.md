You define a consistent product identity to be reused across all landing page images.

- Product description: {{ product_prompt }}
- User clarifications for visuals:
{{ image_follow_up_context }}

Return a short, concrete identity brief (3-6 sentences) that locks in visual details: material, color palette, textures, proportions, branding/markings, and any distinctive features. Keep it photorealistic unless the context says otherwise.

Respond **only** with a JSON object:
{"identity": "<product identity brief>"}
