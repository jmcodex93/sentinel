// Intentionally empty of symbols.
//
// Tsentinelpin.res declares no ids of its own — it is a minimal shell
// (NAME + INCLUDE Tbase + an empty ID_TAGPROPERTIES group) and every
// parameter of this tag is built dynamically in sentinel/ui/pin_tag.py's
// GetDDescription, so there is nothing for a symbol header to define.
//
// Kept rather than deleted because CLAUDE.md's res convention for this repo
// is a .res|.h|.str triplet per registered plugin, and every reference
// plugin checked (this repo's own Tsentinelframe, plus all 20 description
// resources in the Maxon Python API examples clone) ships one. Whether C4D
// strictly requires the file when the .res needs no symbols was NOT
// measured live — deleting it is unverifiable from here and buys nothing.
