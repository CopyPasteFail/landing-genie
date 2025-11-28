You are refining an existing static landing page.

- Existing slug: {{ slug }}
- The landing lives under: sites/{{ slug }}/
- User feedback:

{{ feedback }}

Tasks:

1. Read the existing files in `sites/{{ slug }}/`.
2. Apply incremental edits that address the feedback.
   - Prefer focused changes over a full rewrite.
3. Keep the overall structure: hero, problem, solution, features, social proof, contact form.
4. Ensure the contact form still posts to `/api/contact` with fields: name, email, message.
5. Keep the CSS and JS in separate files.

Use the file tools to update files in `sites/{{ slug }}/` and then output a short summary of what you changed.
