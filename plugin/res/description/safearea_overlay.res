// Resource description for the Sentinel Safe-Area Overlay ObjectData
// plugin. Registered with description="safearea_overlay" so this file's
// basename matches.
//
// The plugin has no user-facing parameters — all overlay state lives in
// the panel's module-level singleton and the Multi-Format Take system.
// We INCLUDE Obase so the object inherits the standard BaseObject
// parameter set (Name, Layer, Display, etc.) for normal Object Manager
// behavior.
CONTAINER safearea_overlay
{
	NAME safearea_overlay;
	INCLUDE Obase;

	GROUP ID_OBJECTPROPERTIES
	{
	}
}
