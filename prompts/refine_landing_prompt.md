You are refining an existing static landing page.

- Existing slug: {{ slug }}
- All files are in the current working directory: sites/{{ slug }}/ (do not create nested `sites/`).
- User feedback:

{{ feedback }}

Tasks:

1. Read the existing files in the current directory.
2. Apply incremental edits that address the feedback.
   - Prefer focused changes over a full rewrite.
3. Keep the overall structure: hero, problem, solution, features, social proof, contact form.
4. Ensure the contact form still posts to `/api/contact` with fields: name, email, message.
5. Keep the CSS and JS in separate files.

Use the file tools to update files in this directory (and its subfolders) and then output a short summary of what you changed.
