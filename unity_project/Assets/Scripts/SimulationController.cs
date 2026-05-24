using UnityEngine;
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

/// <summary>
/// XuanwuAI Simulation Controller — receives demolition commands via TCP
/// and triggers physics-based collapse animations.
///
/// Setup:
/// 1. Attach this script to a GameObject in your Unity scene.
/// 2. Ensure the scene contains a frame structure built from GameObjects
///    with Rigidbody and ConfigurableJoint components.
/// 3. Unity will listen on TCP port 5005 for JSON commands.
///
/// Command format (JSON):
///   {"action": "demolish", "failed_elements": [0, 3], "force_multiplier": 1.5}
///   {"action": "reset"}
/// </summary>
public class SimulationController : MonoBehaviour
{
    [Header("Network Settings")]
    [SerializeField] private int listenPort = 5005;

    [Header("Simulation Settings")]
    [SerializeField] private float defaultExplosionForce = 50000f;
    [SerializeField] private float explosionRadius = 2.5f;
    [SerializeField] private ForceMode forceMode = ForceMode.Impulse;

    [Header("Frame Structure")]
    [Tooltip("Assign all structural elements (columns & beams) in order. " +
             "Element IDs in JSON commands correspond to indices in this array.")]
    [SerializeField] private List<GameObject> structuralElements = new List<GameObject>();

    // TCP listener
    private TcpListener _tcpListener;
    private Thread _listenerThread;
    private bool _isRunning;
    private readonly object _commandLock = new object();
    private string _pendingCommand;

    // Initial state for reset
    private List<TransformSnapshot> _initialStates = new List<TransformSnapshot>();

    private struct TransformSnapshot
    {
        public Vector3 position;
        public Quaternion rotation;
        public Rigidbody rigidbody;
        public Vector3 velocity;
        public Vector3 angularVelocity;
    }

    void Start()
    {
        // Save initial states for reset
        foreach (var element in structuralElements)
        {
            if (element == null) continue;

            var rb = element.GetComponent<Rigidbody>();
            _initialStates.Add(new TransformSnapshot
            {
                position = element.transform.position,
                rotation = element.transform.rotation,
                rigidbody = rb,
                velocity = rb != null ? rb.velocity : Vector3.zero,
                angularVelocity = rb != null ? rb.angularVelocity : Vector3.zero,
            });
        }

        // Start TCP listener in background thread
        _isRunning = true;
        _listenerThread = new Thread(ListenForCommands)
        {
            IsBackground = true,
            Name = "UnityTCPListener"
        };
        _listenerThread.Start();

        Debug.Log($"[XuanwuAI] SimulationController ready on port {listenPort}. " +
                  $"{structuralElements.Count} structural elements tracked.");
    }

    void Update()
    {
        // Process pending commands on the main thread (Unity API is not thread-safe)
        lock (_commandLock)
        {
            if (_pendingCommand == null) return;

            try
            {
                var command = JsonUtility.FromJson<DemolitionCommand>(_pendingCommand);
                if (command != null)
                {
                    ExecuteCommand(command);
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[XuanwuAI] Failed to parse command: {ex.Message}");
            }

            _pendingCommand = null;
        }
    }

    void OnDestroy()
    {
        _isRunning = false;
        _listenerThread?.Join(500);
        _tcpListener?.Stop();
    }

    void OnApplicationQuit()
    {
        _isRunning = false;
        _tcpListener?.Stop();
    }

    private void ListenForCommands()
    {
        try
        {
            _tcpListener = new TcpListener(IPAddress.Any, listenPort);
            _tcpListener.Start();
            Debug.Log($"[XuanwuAI] TCP listener started on port {listenPort}");

            while (_isRunning)
            {
                try
                {
                    using (var client = _tcpListener.AcceptTcpClient())
                    using (var stream = client.GetStream())
                    {
                        var buffer = new byte[8192];
                        var bytesRead = stream.Read(buffer, 0, buffer.Length);
                        var json = Encoding.UTF8.GetString(buffer, 0, bytesRead).Trim();

                        lock (_commandLock)
                        {
                            _pendingCommand = json;
                        }

                        // Send acknowledgment
                        var ack = "{\"status\":\"received\"}\n";
                        var ackBytes = Encoding.UTF8.GetBytes(ack);
                        stream.Write(ackBytes, 0, ackBytes.Length);
                    }
                }
                catch (SocketException)
                {
                    if (!_isRunning) break;
                    Thread.Sleep(100);
                }
            }
        }
        catch (Exception ex)
        {
            Debug.LogError($"[XuanwuAI] TCP listener error: {ex.Message}");
        }
    }

    private void ExecuteCommand(DemolitionCommand command)
    {
        switch (command.action)
        {
            case "demolish":
                DemolishElements(command.failed_elements, command.force_multiplier);
                break;
            case "reset":
                ResetSimulation();
                break;
            case "restart_webrtc":
                RestartWebRTC();
                break;
            default:
                Debug.LogWarning($"[XuanwuAI] Unknown action: {command.action}");
                break;
        }
    }

    /// <summary>
    /// Apply explosive forces to the specified structural elements.
    /// For each failed element, incapacitate its joints and apply forces
    /// to neighboring elements to trigger cascading collapse.
    /// </summary>
    private void DemolishElements(int[] failedElementIds, float forceMultiplier)
    {
        if (forceMultiplier <= 0f) forceMultiplier = 1.5f;

        Debug.Log($"[XuanwuAI] Demolishing elements: [{string.Join(", ", failedElementIds)}] " +
                  $"with force multiplier {forceMultiplier:F1}x");

        var indicesToRemove = new HashSet<int>(failedElementIds);

        for (int i = 0; i < structuralElements.Count; i++)
        {
            var element = structuralElements[i];
            if (element == null) continue;

            var rb = element.GetComponent<Rigidbody>();

            if (indicesToRemove.Contains(i))
            {
                // Disable joints on the failed element to detach from structure
                var joints = element.GetComponents<Joint>();
                foreach (var joint in joints)
                {
                    Destroy(joint);
                }

                // Apply strong outward force
                if (rb != null)
                {
                    var direction = (element.transform.position - GetStructureCenter()).normalized;
                    if (direction.sqrMagnitude < 0.01f)
                        direction = Vector3.right + Vector3.up * 0.3f;

                    rb.AddForce(direction * defaultExplosionForce * forceMultiplier, forceMode);
                    rb.AddTorque(UnityEngine.Random.insideUnitSphere * defaultExplosionForce * 0.3f, forceMode);

                    // Briefly increase mass effect
                    rb.mass *= 0.5f;
                }
            }
            else
            {
                // Nearby elements get shockwave effect
                foreach (var failId in failedElementIds)
                {
                    if (failId < structuralElements.Count)
                    {
                        var failedElement = structuralElements[failId];
                        if (failedElement == null) continue;

                        var distance = Vector3.Distance(
                            element.transform.position,
                            failedElement.transform.position);

                        if (distance < explosionRadius && rb != null)
                        {
                            var shockwaveDir = (element.transform.position -
                                failedElement.transform.position).normalized;
                            var attenuatedForce = defaultExplosionForce * forceMultiplier *
                                (1f - distance / explosionRadius) * 0.5f;
                            rb.AddForce(shockwaveDir * attenuatedForce, forceMode);
                        }
                    }
                }
            }
        }

        Debug.Log($"[XuanwuAI] Demolition executed on {failedElementIds.Length} element(s).");
    }

    /// <summary>
    /// Reset all structural elements to their initial positions and states.
    /// </summary>
    private void ResetSimulation()
    {
        Debug.Log("[XuanwuAI] Resetting simulation...");

        for (int i = 0; i < structuralElements.Count && i < _initialStates.Count; i++)
        {
            var element = structuralElements[i];
            var snapshot = _initialStates[i];
            if (element == null) continue;

            element.transform.position = snapshot.position;
            element.transform.rotation = snapshot.rotation;

            if (snapshot.rigidbody != null)
            {
                snapshot.rigidbody.velocity = Vector3.zero;
                snapshot.rigidbody.angularVelocity = Vector3.zero;
                snapshot.rigidbody.mass = 1f;
            }
        }

        Debug.Log("[XuanwuAI] Simulation reset complete.");
    }

    private void RestartWebRTC()
    {
        var streamer = FindObjectOfType<WebRTCStreamer>();
        if (streamer != null)
        {
            Debug.Log("[XuanwuAI] Restarting WebRTC streaming...");
            streamer.RestartStreaming();
        }
        else
        {
            Debug.LogWarning("[XuanwuAI] WebRTCStreamer not found — cannot restart.");
        }
    }

    private Vector3 GetStructureCenter()
    {
        if (structuralElements.Count == 0)
            return transform.position;

        var center = Vector3.zero;
        int count = 0;
        foreach (var element in structuralElements)
        {
            if (element != null)
            {
                center += element.transform.position;
                count++;
            }
        }
        return count > 0 ? center / count : transform.position;
    }

    // --- JSON serialization classes ---

    [Serializable]
    private class DemolitionCommand
    {
        public string action;
        public int[] failed_elements;
        public float force_multiplier = 1.5f;
    }

    // Helper to convert JSON naming convention
    private static DemolitionCommand ParseJson(string json)
    {
        // Unity's JsonUtility expects camelCase, but our API uses snake_case.
        // Use a wrapper approach
        var wrapper = JsonUtility.FromJson<DemolitionCommandWrapper>(json);
        return new DemolitionCommand
        {
            action = wrapper?.action,
            failed_elements = wrapper?.failed_elements,
            force_multiplier = wrapper?.force_multiplier ?? 1.5f,
        };
    }

    [Serializable]
    private class DemolitionCommandWrapper
    {
        public string action;
        public int[] failed_elements;
        public float force_multiplier = 1.5f;
    }
}
