You are crafting a Gemini Image prompt for a landing page asset.

- Product description: {{ product_prompt }}
- Image slot path: {{ slot_src }}
- Alt text / intent: {{ slot_alt }}
- User clarifications for visuals:
{{ image_follow_up_context }}

Write a single, vivid prompt (1-2 sentences) for the Gemini Image model. Make it photorealistic unless the context specifies otherwise. Avoid any text overlays and keep backgrounds clean. If this is a hero slot, note a wide 16:9 composition; otherwise keep the palette cohesive with the page style. Reflect the clarifications above.

Respond **only** with a JSON object:
{"prompt": "<final prompt to send to Gemini Image model>"}
