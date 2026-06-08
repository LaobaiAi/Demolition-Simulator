using UnityEngine;
using UnityEditor;
using UnityEngine.SceneManagement;

/// <summary>
/// One-click scene setup for XuanwuAI Demolition Simulator.
/// Menu: Tools → XuanwuAI → Setup Scene
///
/// Creates:
///   - Main Camera with WebRTCStreamer
///   - SimulationController + FrameBuilder on a root GameObject
///   - Directional Light
///   - Ground plane
///   - Calls BuildFrame() to generate the structure
/// </summary>
public static class XuanwuAISceneSetup
{
    [MenuItem("Tools/XuanwuAI/Setup Scene")]
    public static void SetupScene()
    {
        // --- Clear existing XuanwuAI objects ---
        var existing = GameObject.Find("XuanwuAISimulation");
        if (existing != null)
            Object.DestroyImmediate(existing);

        var existingCam = GameObject.Find("XuanwuAICamera");
        if (existingCam != null)
            Object.DestroyImmediate(existingCam);

        // --- Create root GameObject ---
        var root = new GameObject("XuanwuAISimulation");
        var controller = root.AddComponent<SimulationController>();
        var builder = root.AddComponent<FrameBuilder>();

        // --- Create dedicated camera with WebRTC streamer ---
        var camGo = new GameObject("XuanwuAICamera");
        camGo.tag = "MainCamera";
        var cam = camGo.AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.53f, 0.81f, 0.98f);
        cam.transform.position = new Vector3(6f, 4f, -15f);
        cam.transform.LookAt(new Vector3(6f, 3f, 0f));
        camGo.AddComponent<FrameServer>();

        // --- Lighting ---
        var lightGo = GameObject.Find("XuanwuAILight");
        if (lightGo == null)
        {
            lightGo = new GameObject("XuanwuAILight");
            var dl = lightGo.AddComponent<Light>();
            dl.type = LightType.Directional;
            dl.intensity = 1.2f;
            dl.shadows = LightShadows.Soft;
            lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
        }

        // --- Ground plane ---
        var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
        ground.name = "GroundPlane";
        ground.transform.position = new Vector3(6f, -0.1f, 0f);
        ground.transform.localScale = new Vector3(3f, 1f, 2f);
        var groundRenderer = ground.GetComponent<Renderer>();
        if (groundRenderer != null)
        {
            var mat = new Material(Shader.Find("Standard"));
            mat.color = new Color(0.15f, 0.15f, 0.18f);
            groundRenderer.material = mat;
        }
        ground.transform.SetParent(root.transform);

        // --- Build frame ---
        // Don't build demo frame — wait for frontend to send structure via build_frame TCP command
        // builder.BuildFrame();

        // --- Select the camera ---
        Selection.activeGameObject = camGo;

        Debug.Log("[XuanwuAI] Scene setup complete — waiting for structure from frontend.");
        Debug.Log("[XuanwuAI] Camera: " + camGo.name + " | TCP: port 5005 | FrameServer: port 5006");
    }

    [MenuItem("Tools/XuanwuAI/Reset Simulation")]
    public static void ResetSimulation()
    {
        var root = GameObject.Find("XuanwuAISimulation");
        if (root == null)
        {
            Debug.LogWarning("[XuanwuAI] No simulation found. Run Setup Scene first.");
            return;
        }

        var controller = root.GetComponent<SimulationController>();
        if (controller != null)
        {
            // Rebuild frame
            var builder = root.GetComponent<FrameBuilder>();
            if (builder != null)
                builder.BuildFrame();
        }

        Debug.Log("[XuanwuAI] Simulation reset.");
    }
}
