You are generating a static landing page for a product.

- Product description: {{ product_prompt }}
- Product type: {{ product_type }}
- Target subdomain: {{ slug }}.{{ root_domain }}
- Current working directory: sites/{{ slug }}/ (write all files here; do not create nested `sites/`).

Tasks:

1. Ensure the current directory contains:
   - index.html
   - styles.css
   - main.js
   - Optional images in `assets/`.

2. The HTML must:
   - Link the CSS and JS files correctly.
   - Contain sections: hero, problem, solution, features, social proof, contact form.

3. The contact form must:
   - Use `<form action="/api/contact" method="POST">`.
   - Include fields for name, email, and optional message.
   - Include basic client side validation in `main.js`.

4. Use modern CSS with responsive layout for desktop, tablet, and mobile.

5. For visuals:
   - Assume a separate process will generate actual image files.
   - Create placeholder `<img>` tags pointing to `assets/hero.png`, `assets/feature-1.png`, etc.

6. Use the file tools to create and write these files in the current directory (and its `assets/` subfolder).
   - If files already exist, update them rather than deleting everything unless a full rewrite is needed.

At the end, output a short summary of what you created or changed.
