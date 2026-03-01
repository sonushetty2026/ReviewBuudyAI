import { ARPlacement, ARSessionState, DeviceTier } from '@/types';

/**
 * AR Engine — wraps WebXR session management for ground-plane detection,
 * hit-testing, and avatar anchoring.
 */
export class AREngine {
  private xrSession: XRSession | null = null;
  private xrRefSpace: XRReferenceSpace | null = null;
  private hitTestSource: XRHitTestSource | null = null;
  private placement: ARPlacement | null = null;
  private deviceTier: DeviceTier;
  private onStateChange: (state: ARSessionState) => void;
  private onPlacementUpdate: (placement: ARPlacement) => void;
  private gl: WebGL2RenderingContext | null = null;

  constructor(
    deviceTier: DeviceTier,
    onStateChange: (state: ARSessionState) => void,
    onPlacementUpdate: (placement: ARPlacement) => void
  ) {
    this.deviceTier = deviceTier;
    this.onStateChange = onStateChange;
    this.onPlacementUpdate = onPlacementUpdate;
  }

  /**
   * Starts a WebXR immersive-ar session with hit-test and optional depth sensing.
   */
  async startSession(canvas: HTMLCanvasElement): Promise<boolean> {
    if (!navigator.xr) {
      this.onStateChange(ARSessionState.ERROR);
      return false;
    }

    try {
      this.onStateChange(ARSessionState.INITIALIZING);

      this.gl = canvas.getContext('webgl2', { xrCompatible: true }) as WebGL2RenderingContext;
      if (!this.gl) {
        this.onStateChange(ARSessionState.ERROR);
        return false;
      }

      // Build required/optional features based on device tier
      const requiredFeatures: string[] = ['hit-test', 'local-floor'];
      const optionalFeatures: string[] = ['anchors', 'dom-overlay'];

      if (this.deviceTier === DeviceTier.TIER_1_CINEMATIC) {
        optionalFeatures.push('depth-sensing', 'light-estimation');
      }

      this.xrSession = await navigator.xr!.requestSession('immersive-ar', {
        requiredFeatures,
        optionalFeatures,
        domOverlay: { root: document.getElementById('ar-overlay')! },
      });

      this.xrSession.addEventListener('end', () => this.handleSessionEnd());

      // Set up WebGL layer
      const xrLayer = new XRWebGLLayer(this.xrSession, this.gl);
      await this.xrSession.updateRenderState({ baseLayer: xrLayer });

      // Get reference space
      this.xrRefSpace = await this.xrSession.requestReferenceSpace('local-floor');

      // Start hit testing for ground plane detection
      await this.setupHitTest();

      this.onStateChange(ARSessionState.CALIBRATING);
      return true;
    } catch (err) {
      console.error('Failed to start AR session:', err);
      this.onStateChange(ARSessionState.ERROR);
      return false;
    }
  }

  /**
   * Sets up a hit-test source pointing downward to detect the ground plane.
   */
  private async setupHitTest(): Promise<void> {
    if (!this.xrSession) return;

    const viewerSpace = await this.xrSession.requestReferenceSpace('viewer');
    this.hitTestSource = await this.xrSession.requestHitTestSource!({
      space: viewerSpace,
    });
  }

  /**
   * Called per-frame during the XR render loop to process hit-test results.
   * Returns the latest detected ground position, or null if none found.
   */
  processFrame(frame: XRFrame): ARPlacement | null {
    if (!this.hitTestSource || !this.xrRefSpace) return null;

    const hitResults = frame.getHitTestResults(this.hitTestSource);
    if (hitResults.length === 0) return null;

    const hit = hitResults[0];
    const pose = hit.getPose(this.xrRefSpace);
    if (!pose) return null;

    const t = pose.transform;
    return {
      position: {
        x: t.position.x,
        y: t.position.y,
        z: t.position.z,
      },
      rotation: {
        x: t.orientation.x,
        y: t.orientation.y,
        z: t.orientation.z,
        w: t.orientation.w,
      },
      scale: 1.0,
      anchorId: null,
    };
  }

  /**
   * Anchors the digital human at the given placement.
   * Creates a persistent WebXR anchor if supported.
   */
  async anchorPlacement(placement: ARPlacement, frame: XRFrame): Promise<ARPlacement> {
    this.placement = { ...placement };

    // Try to create a persistent anchor
    if (this.xrSession && 'createAnchor' in frame) {
      try {
        const pose = new XRRigidTransform(
          placement.position,
          placement.rotation
        );
        const anchor = await (frame as any).createAnchor(pose, this.xrRefSpace);
        this.placement.anchorId = anchor?.anchorSpace ? 'anchored' : null;
      } catch {
        // Anchoring not supported, position-only fallback
      }
    }

    this.onPlacementUpdate(this.placement);
    this.onStateChange(ARSessionState.ANCHORED);
    return this.placement;
  }

  /**
   * Returns the current placement.
   */
  getPlacement(): ARPlacement | null {
    return this.placement;
  }

  /**
   * Ends the current AR session.
   */
  async endSession(): Promise<void> {
    if (this.hitTestSource) {
      this.hitTestSource.cancel();
      this.hitTestSource = null;
    }
    if (this.xrSession) {
      await this.xrSession.end();
      this.xrSession = null;
    }
  }

  private handleSessionEnd(): void {
    this.xrSession = null;
    this.hitTestSource = null;
    this.xrRefSpace = null;
    this.onStateChange(ARSessionState.COMPLETED);
  }

  /**
   * Returns whether the session is active.
   */
  isActive(): boolean {
    return this.xrSession !== null;
  }
}
