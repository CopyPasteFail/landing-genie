Your job is to decide which landing-page image slots must depict the product or real UI,
based only on each slot’s alt text and draft prompt.
This decision is used to inject a canonical product image reference only where needed.

Product description:
{{ product_prompt }}

What counts as “depicts the product”:
- Physical product: the actual item or its packaging is clearly visible.
- Software/app: a real UI, screenshot, or mockup of the product is clearly visible.

Slots are listed in page order. Each slot includes src, alt text, and the draft prompt:
{{ slot_list }}

Task:
- Return product_slots as a list of slot src values that require the product to be visible.
- Choose canonical_src as the earliest src in product_slots.

Rules:
1) Only use src values that appear in the provided slot list. Do not invent paths.
2) Include a slot in product_slots only if its alt text or draft prompt explicitly implies the product or UI is visible.
3) Prefer hero or primary slots first, then feature slots, then other sections.
4) Negative keyword rule:
   If alt or prompt contains any of:
   background, abstract, pattern, texture, gradient, wave, divider, ornament,
   decorative, stock photo, generic, illustration
   then exclude the slot from product_slots
   unless it also contains at least one of:
   product, packaging, screenshot, UI, app screen, mockup, device showing

Respond with JSON only, with exactly these keys:
{
  "canonical_src": "assets/hero.png",
  "product_slots": ["assets/hero.png", "assets/feature-1.png"]
}

If no slot requires the product to be visible, return exactly:
{"canonical_src":"","product_slots":[]}
