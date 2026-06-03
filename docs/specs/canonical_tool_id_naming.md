# Canonical Tool ID Naming

1. Canonical tool IDs are the only stable public tool identifiers.
2. Format: lowercase `snake_case` runtime name.
3. Canonical IDs align with the Neurodesk-facing module command name.
4. Prefer `<package>_<command>` when the command is package-specific.
5. Do not encode versions in canonical IDs.
6. Do not expose planner/catalog `*.run` IDs as public tool IDs.
7. Do not expose NiWrap versioned descriptor IDs as public tool IDs.
8. Legacy planner/catalog IDs are ingress-only compatibility aliases.
9. New tools must define a canonical runtime ID before any alias mappings.
10. Examples: `fsl_bet`, `cat12_segment`, `ants_registration`.
