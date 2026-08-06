# Source attribution and redistribution boundary

This export redistributes the audit design, project-authored adjudication
summaries, public identifiers or URLs, and final verdicts. It does not
redistribute raw upstream tables, abstracts, evidence quotes, neuroimaging
files, ontology dumps, private KG properties, or internal generation payloads.

The repository's MIT license covers Brain Researcher-authored code and text. It
does not replace the terms of upstream sources. Where an upstream license was
not fixed in the audit capture, this export makes no license assertion and
omits the raw source content.

| Source family | Audit role | Public reference | Version or capture boundary | Redistribution statement |
|---|---|---|---|---|
| Neurosynth | Bibliographic metadata, coordinates, and abstract-derived TF-IDF checks | [Neurosynth data repository](https://github.com/neurosynth/neurosynth-data) | Fixed v7 source used by the private audit | Selected factual values, including PMIDs, coordinates, source-space labels, and TF-IDF metadata names, appear in the public adjudication ledger. No bulk source files or full upstream tables are included. |
| NeuroVault | Collection and statistical-image metadata checks | [NeuroVault](https://neurovault.org/) | Public API records observed by the audit | Only public URLs, image IDs, and project-authored summaries are included. |
| NeuroStore | Base-study title, task, domain, and pipeline-result checks | [NeuroStore](https://neurostore.org/) | Public API records observed by the audit | No API payload or bulk metadata is redistributed; license is not asserted here. |
| OpenNeuro and OpenNeuroDatasets | Dataset and derived-map provenance checks | [OpenNeuro](https://openneuro.org/) | Dataset identifiers recorded by the audit | No raw dataset files or subject identifiers are included; consult each dataset's own license and citation. |
| Cognitive Atlas and ONVOC mappings | Task and concept classification checks | [Cognitive Atlas](https://www.cognitiveatlas.org/) | Public concept/task records and the audited mapping snapshot | No ontology dump is included; license is not asserted by this export. |
| PubMed and PubMed Central | Citation, title, and source-support checks | [PubMed](https://pubmed.ncbi.nlm.nih.gov/) and [PMC](https://pmc.ncbi.nlm.nih.gov/) | Public records linked by PMID or PMC ID | Citation identifiers and links are included; abstracts and long source quotes are not redistributed. |
| NiCLIP mapping | Embedding-row identity checks | Not redistributed | Private fixed mapping used by the audit | Only the defect classification and project-authored explanation are public. |
| OpenNeuro GLM/FitLins and Yeo-17 derived records | Map-space, resource, and region provenance checks | Public dataset identifiers where available | Private fixed derived-record snapshot used by the audit | Maps, subject-level locators, atlas assets, and derived tables are not included. |
| Internal extraction and claim-generation records | Claim, evidence, method-condition, and provenance checks | Not redistributed | Private fixed audit evidence | Run IDs, prompts, raw responses, generated IDs, and extracted payloads are omitted. |
| Brain Researcher source code | ETL and schema path inspection | [brain-researcher-public](https://github.com/brain-researcher/brain-researcher-public) | Commit containing this export | Repository-tracked code locators are retained under the repository license. |

Public links are evidence locators, not a claim that the linked content is
licensed under MIT or archived permanently by this repository.

## Neurosynth notice

This audit contains information from the Neurosynth database, which is made
available under the [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/).
The upstream [Neurosynth data repository](https://github.com/neurosynth/neurosynth-data)
provides the database and its license notice. The repository's MIT license
applies only to Brain Researcher-authored text and code; it does not relicense
Neurosynth-derived factual content. This notice is included conservatively and
does not attempt to classify this audit export legally as a Produced Work or a
Derivative Database.
