using UnityEditor;
using UnityEngine;
using System.IO;

[InitializeOnLoad]
public static class AutoPlayOnLoad
{
    private const string FLAG_PATH = "auto_play.flag";
    private const string PREFS_ACTIVE = "XuanwuAI_AutoPlay_Active";
    private static double _startTime;
    private static bool _triggered;
    private static double _exitTime;
    private static bool _pendingReEnter;

    static AutoPlayOnLoad()
    {
        _startTime = EditorApplication.timeSinceStartup;
        EditorApplication.update += Poll;
        EditorApplication.playModeStateChanged += OnPlayModeChanged;
        Debug.Log("[XuanwuAI] AutoPlayOnLoad registered — " + FLAG_PATH);
    }

    private static void Poll()
    {
        if (_triggered) return;
        if (EditorApplication.timeSinceStartup - _startTime < 4.0) return;
        if (!File.Exists(FLAG_PATH)) return;

        _triggered = true;
        EditorApplication.update -= Poll;

        Debug.Log("[XuanwuAI] Auto-play flag detected — setup + play...");

        try
        {
            XuanwuAISceneSetup.SetupScene();
        }
        catch (System.Exception e)
        {
            Debug.LogError("[XuanwuAI] Auto-setup failed: " + e.Message);
            _triggered = false;
            EditorApplication.update += Poll;
            return;
        }

        EditorPrefs.SetBool(PREFS_ACTIVE, true);
        EditorApplication.EnterPlaymode();
        Debug.Log("[XuanwuAI] Entering Play mode...");
    }

    private static void OnPlayModeChanged(PlayModeStateChange state)
    {
        if (state == PlayModeStateChange.EnteredPlayMode)
        {
            if (File.Exists(FLAG_PATH)) File.Delete(FLAG_PATH);
            _pendingReEnter = false;
        }
        else if (state == PlayModeStateChange.ExitingPlayMode)
        {
            if (EditorPrefs.GetBool(PREFS_ACTIVE, false))
            {
                _exitTime = EditorApplication.timeSinceStartup;
                EditorApplication.update += DelayedReEnter;
                _pendingReEnter = true;
            }
        }
        else if (state == PlayModeStateChange.EnteredEditMode)
        {
            if (_pendingReEnter && !_triggered)
            {
                _triggered = true;
                EditorApplication.EnterPlaymode();
            }
        }
    }

    private static void DelayedReEnter()
    {
        if (_pendingReEnter && EditorApplication.timeSinceStartup - _exitTime > 5.0)
        {
            _pendingReEnter = false;
            EditorApplication.update -= DelayedReEnter;
            EditorApplication.EnterPlaymode();
            Debug.Log("[XuanwuAI] Auto re-entered Play mode");
        }
    }

    [MenuItem("Tools/XuanwuAI/Toggle Auto-Play %#p")]
    private static void ToggleAutoPlay()
    {
        bool active = EditorPrefs.GetBool(PREFS_ACTIVE, false);
        EditorPrefs.SetBool(PREFS_ACTIVE, !active);
        Debug.Log("[XuanwuAI] Auto-play " + (!active ? "ENABLED" : "DISABLED"));
    }
}
