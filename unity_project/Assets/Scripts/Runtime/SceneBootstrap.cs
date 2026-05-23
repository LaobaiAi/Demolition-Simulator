using UnityEngine;

/// <summary>
/// Ensures the simulation scene is set up at runtime.
/// If the scene was already configured via Editor tool, this is a no-op.
/// If not (e.g. first run), creates the essential simulation objects.
/// </summary>
public static class SceneBootstrap
{
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void OnRuntimeLoad()
    {
        var existing = GameObject.Find("XuanwuAISimulation");
        if (existing != null) return; // Already set up

        Debug.Log("[XuanwuAI] Bootstrapping simulation scene at runtime...");

        var root = new GameObject("XuanwuAISimulation");
        root.AddComponent<SimulationController>();
        var builder = root.AddComponent<FrameBuilder>();

        // Camera
        var camGo = new GameObject("XuanwuAICamera");
        var cam = camGo.AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.04f, 0.06f, 0.1f);
        cam.transform.position = new Vector3(6f, 4f, -15f);
        cam.transform.LookAt(new Vector3(6f, 3f, 0f));
        var streamer = camGo.AddComponent<WebRTCStreamer>();
        camGo.AddComponent<WebRTCSignaling>();

        // Light
        var lightGo = new GameObject("XuanwuAILight");
        var dl = lightGo.AddComponent<Light>();
        dl.type = LightType.Directional;
        dl.intensity = 1.2f;
        dl.shadows = LightShadows.Soft;
        lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        // Ground
        var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
        ground.name = "GroundPlane";
        ground.transform.position = new Vector3(6f, -0.1f, 0f);
        ground.transform.localScale = new Vector3(3f, 1f, 2f);
        var renderer = ground.GetComponent<Renderer>();
        if (renderer != null)
        {
            var mat = new Material(Shader.Find("Standard"));
            mat.color = new Color(0.15f, 0.15f, 0.18f);
            renderer.material = mat;
        }
        ground.transform.SetParent(root.transform);

        // Build frame
        builder.BuildFrame();

        Debug.Log("[XuanwuAI] Runtime bootstrap complete.");
    }
}
