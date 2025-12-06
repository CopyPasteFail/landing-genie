You are preparing to write a landing page. Before drafting, surface every clarification needed to nail the copy, structure, and visuals.

- Product description: {{ product_prompt }}

Ask up to {{ max_follow_up_questions }} focused questions. Make them specific and actionable so the user can define the page quickly. Cover audience, problem/promise, product stage and key proof, offer/pricing, primary CTA, tone/brand cues, visual/style preferences, sections to prioritize (hero, social proof, features, FAQ, contact), and any constraints (compliance, accessibility, timelines). Offer brief choice sets where helpful (e.g., tone: authoritative vs. playful vs. minimalist; CTA style: button vs. form vs. scheduler) and note what each choice enables (authoritative = trust/rigor, playful = warmth/approachability, minimalist = clarity/speed).
Include a question that clarifies the product type (e.g., software, hardware, service, hybrid) and how that affects messaging (e.g., software = demo/interactive CTA, hardware = specs/shipping, service = credibility/process).

Respond **only** with a JSON object of the form:
{"questions": ["...", "...", "..."]}

Do not use file tools and avoid any extra commentary.
