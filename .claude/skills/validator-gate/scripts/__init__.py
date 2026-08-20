"""validator-gate skill runtime package.

The single behavior source is the `validator` CLI (added in a later slice);
everything else here is library code it imports: contracts, the evidence-pack
reader, the claim/artifact index, the router, the semantic families, the result
composer, and the Execution Loop adapter. Stdlib-only, offline, deterministic.
"""
