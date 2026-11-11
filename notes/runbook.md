> 2026-11-11 (Hark) : consigne actuelle de Karim — le front et l'API sont sur Render (autodeploy de main, push autorisé après chaque livraison testée) ; Netlify n'est plus utilisé (redirection 301). Les étapes Netlify ci-dessous sont obsolètes.

# Draft release and QA

1. Run `cd web && npm ci && npm run build`. Confirm the web 3D implementation is emitted as its own asset chunk before publishing; do not treat CSS selectors as proof that the 3D feature is present.
2. From the repository root, run `source .venv/bin/activate && pytest tests/ --ignore=tests/test_gui.py -q`.
3. Package the contents of `web/dist` at the ZIP root and upload it only as a Netlify draft deployment. Never publish or promote the draft to production as part of QA.
4. On the draft, verify the fixes from commit `0a9ef34`, then check editor tools, undo/redo, measurement persistence and PNG/PDF export, and 3D in both the editor and twin.
5. After QA, remove the named E2E accounts, workshops, plan, and plan-background object from Supabase Storage; verify their absence.
6. Do not push to `main` while Render auto-deploys that branch unless a production API deployment is explicitly approved.

Do not store access tokens in this runbook or in source control.