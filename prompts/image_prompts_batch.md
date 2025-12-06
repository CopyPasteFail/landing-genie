You generate detailed image prompts for a landing page.

- Product description: {{ product_prompt }}
- Follow-up context: {{ image_follow_up_context }}
- Image slots (src, alt/title/hint):
{{ slot_list }}

Output JSON only in this shape:
{
  "prompts": [
    { "src": "<src from above>", "prompt": "<rich image prompt>" },
    ...
  ]
}

Rules:
- Include every listed src exactly once.
- Make prompts vivid, photorealistic by default; reflect provided alt text.
- Keep prompts under ~80 words each.
