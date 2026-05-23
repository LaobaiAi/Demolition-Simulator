using UnityEditor;
using UnityEngine;
using System.IO;

[InitializeOnLoad]
public static class AutoPlayOnLoad
{
    private const string FLAG_PATH = "Temp/auto_play.flag";
    private static double _startTime;
    private static bool _triggered;

    static AutoPlayOnLoad()
    {
        _startTime = EditorApplication.timeSinceStartup;
        EditorApplication.update += Poll;
        Debug.Log("[XuanwuAI] AutoPlayOnLoad registered — waiting for flag: " + FLAG_PATH);
    }

    private static void Poll()
    {
        if (_triggered) return;

        // Wait 4 seconds for editor to stabilize after compilation
        if (EditorApplication.timeSinceStartup - _startTime < 4.0) return;

        if (!File.Exists(FLAG_PATH)) return;

        _triggered = true;
        EditorApplication.update -= Poll;

        Debug.Log("[XuanwuAI] Auto-play flag detected — setting up scene...");

        try
        {
            XuanwuAISceneSetup.SetupScene();
        }
        catch (System.Exception e)
        {
            Debug.LogError($"[XuanwuAI] Auto-setup failed: {e.Message}");
            _triggered = false;
            EditorApplication.update += Poll;
            return;
        }

        EditorApplication.playModeStateChanged += OnPlayModeChanged;
        EditorApplication.EnterPlaymode();
        Debug.Log("[XuanwuAI] Entering Play mode...");
    }

    private static void OnPlayModeChanged(PlayModeStateChange state)
    {
        if (state == PlayModeStateChange.EnteredPlayMode)
        {
            EditorApplication.playModeStateChanged -= OnPlayModeChanged;
            if (File.Exists(FLAG_PATH))
            {
                File.Delete(FLAG_PATH);
                Debug.Log("[XuanwuAI] Play mode entered — flag deleted.");
            }
        }
        else if (state == PlayModeStateChange.ExitingEditMode)
        {
            if (File.Exists(FLAG_PATH))
                File.Delete(FLAG_PATH);
        }
    }
}
