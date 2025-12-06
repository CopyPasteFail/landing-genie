You are generating a static landing page for a product.

- Product description: {{ product_prompt }}
- Target subdomain: {{ slug }}.{{ root_domain }}
{{ follow_up_block }}

- Current working directory: sites/{{ slug }}/ (write all files here; do not create nested `sites/`).

Tasks:

1. Ensure the current directory contains:
   - index.html
   - styles.css
   - main.js
   - Optional images in `assets/`.

2. The HTML must:
   - Link the CSS and JS files correctly.
   - Contain sections: hero, problem, solution, features, credibility/social proof (see rules below), contact form.

3. The contact form must:
   - Use `<form action="/api/contact" method="POST">`.
   - Include fields for name, email, phone (optional), and optional message.
   - Show a phone hint/placeholder of `+1-123456789` and allow only digits and hyphens with an optional leading `+`.
   - Include basic client side validation in `main.js`, including the phone format rule above when a phone number is provided.

4. Use modern CSS with responsive layout for desktop, tablet, and mobile.

5. For visuals:
   - Assume a separate process will generate actual image files.
   - Create placeholder `<img>` tags pointing to `assets/hero.png`, `assets/feature-1.png`, etc.

6. Use the file tools to create and write these files in the current directory (and its `assets/` subfolder).
   - If files already exist, update them rather than deleting everything unless a full rewrite is needed.

Credibility / social proof rules:
- If the product is clearly launched or has usage/metrics context, you may generate testimonial-style social proof.
- For pre-order/early-stage cases with no real users, do not invent testimonials. Use credible alternatives instead: traction proxies (e.g., waitlist size, pilot partners, shipping timeline), founder/problem-origin story with roadmap, quality/standard signals (tech stack, benchmarks), guarantee/refund and support info.
- If none of the above apply, omit the section gracefully rather than fabricating names, quotes, or companies.

At the end, output a short summary of what you created or changed.
