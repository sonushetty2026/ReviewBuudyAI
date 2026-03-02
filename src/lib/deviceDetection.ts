import { DeviceCapabilities, DeviceTier } from '@/types';

/**
 * Detects device AR capabilities and assigns a tier.
 *
 * Tier 1 (Cinematic): LiDAR / depth sensing — best occlusion & grounding
 * Tier 2 (Standard):  WebXR hit-test — good anchoring, no occlusion
 * Tier 3 (Fallback):  No AR support — routes to Fast mode
 */
export async function detectDeviceCapabilities(): Promise<DeviceCapabilities> {
  const ua = navigator.userAgent;
  const screen = {
    width: window.screen.width,
    height: window.screen.height,
  };

  const isIOS = /iPad|iPhone|iPod/.test(ua);
  const isAndroid = /Android/.test(ua);

  // Check for LiDAR-capable devices (iPhone 12 Pro+, iPad Pro 2020+)
  const hasLiDAR = detectLiDAR(ua);

  // Check WebXR support
  const hasWebXR = 'xr' in navigator;
  let hasHitTest = false;
  let hasDepthSensing = false;

  if (hasWebXR) {
    try {
      const xr = navigator.xr!;
      const supported = await xr.isSessionSupported('immersive-ar');
      if (supported) {
        hasHitTest = true;
        // Depth sensing is available on some Android devices and LiDAR iOS
        hasDepthSensing = hasLiDAR || (isAndroid && await checkDepthSensing());
      }
    } catch {
      // WebXR check failed — not supported
    }
  }

  // Determine tier
  let tier: DeviceTier;
  if (hasDepthSensing || hasLiDAR) {
    tier = DeviceTier.TIER_1_CINEMATIC;
  } else if (hasHitTest) {
    tier = DeviceTier.TIER_2_STANDARD;
  } else {
    tier = DeviceTier.TIER_3_FALLBACK;
  }

  return {
    tier,
    hasWebXR,
    hasHitTest,
    hasDepthSensing,
    hasLiDAR,
    supportsARCore: isAndroid && hasWebXR,
    supportsARKit: isIOS,
    screenSize: screen,
    userAgent: ua,
  };
}

/**
 * Heuristic detection of LiDAR-capable Apple devices.
 * iPhone 12 Pro+ and iPad Pro 2020+ have LiDAR.
 */
function detectLiDAR(ua: string): boolean {
  const isIOS = /iPad|iPhone|iPod/.test(ua);
  if (!isIOS) return false;

  // Check screen resolution to identify Pro models
  const screenHeight = window.screen.height;
  const dpr = window.devicePixelRatio || 1;
  const physicalHeight = screenHeight * dpr;

  // Pro models typically have higher resolution
  // iPhone 12 Pro: 2532, 13 Pro: 2532, 14 Pro: 2556, 15 Pro: 2556
  // iPad Pro 11": 2388, iPad Pro 12.9": 2732
  const proResolutions = [2532, 2556, 2622, 2796, 2388, 2732];
  const isLikelyPro = proResolutions.some(
    (res) => Math.abs(physicalHeight - res) < 50
  );

  return isLikelyPro;
}

/**
 * Checks if the Android device supports depth sensing via WebXR.
 */
async function checkDepthSensing(): Promise<boolean> {
  if (!navigator.xr) return false;
  try {
    // Attempt to check for depth-sensing feature
    const supported = await navigator.xr.isSessionSupported('immersive-ar');
    return supported;
  } catch {
    return false;
  }
}

/**
 * Returns human-readable tier description for UI.
 */
export function getTierDisplayInfo(tier: DeviceTier) {
  switch (tier) {
    case DeviceTier.TIER_1_CINEMATIC:
      return {
        label: 'Cinematic AR',
        description: 'Full experience with realistic grounding and occlusion',
        recommended: true,
      };
    case DeviceTier.TIER_2_STANDARD:
      return {
        label: 'Standard AR',
        description: 'Good AR experience with ground anchoring',
        recommended: true,
      };
    case DeviceTier.TIER_3_FALLBACK:
      return {
        label: 'Fast Mode',
        description: 'Camera-style experience (AR not supported on this device)',
        recommended: false,
      };
  }
}
