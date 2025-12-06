You are planning the visuals for a landing page. Before writing image prompts, gather any missing details.

- Product description: {{ product_prompt }}

Ask up to {{ max_follow_up_questions }} concise questions focused on visual direction: subject specifics, mood/lighting, style (e.g., cinematic, illustrative, photorealistic), color palette/brand constraints, representation/diversity needs, layout/composition (wide hero vs. supporting spot), what to avoid, and any accessibility or compliance considerations. Keep questions actionable and offer brief option ranges (e.g., "dark luxe vs. bright minimal") so the user can choose quickly. Where helpful, mention what different choices enable (cinematic = drama/motion, flat illustration = clarity/modularity, muted palette = calm/approachable). Encourage precision to help the user hone instructions.

Respond **only** with a JSON object of the form:
{"questions": ["...", "...", "..."]}
