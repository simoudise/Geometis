# Working rules for this repository

- Code and ontologies only. Never commit trip data, coordinates, geohashes, device identifiers, query outputs or credentials.
- Client data never leaves Synapse machines. Code that reads trip tables runs on the Mac mini through the job runner and writes aggregates only.
- API keys come from environment variables, never from files in the repository.
- Flag gaps against the architecture document (v19) rather than papering over them.
- Write in plain English. Every sentence has a subject doing something; no consultant lingo.
