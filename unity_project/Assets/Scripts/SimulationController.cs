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
    [SerializeField] private float defaultExplosionForce = 2000f;
    [SerializeField] private float explosionRadius = 2.5f;
    [SerializeField] private ForceMode forceMode = ForceMode.Impulse;
    [SerializeField] private DemolitionStyle demolitionStyle = DemolitionStyle.Collapse;

    private enum DemolitionStyle
    {
        Collapse,
        Explosive
    }

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
                DemolitionCommand command = null;
                try
                {
                    command = JsonUtility.FromJson<DemolitionCommand>(_pendingCommand);
                }
                catch
                {
                    command = TryParseManually(_pendingCommand);
                }

                if (command != null)
                {
                    command._rawJson = _pendingCommand;
                    ExecuteCommand(command);
                }
                else
                {
                    Debug.LogWarning($"[XuanwuAI] Unparseable command: {_pendingCommand}");
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[XuanwuAI] Command execution error: {ex.Message}");
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
                if (command.style == "explosive")
                    demolitionStyle = DemolitionStyle.Explosive;
                else
                    demolitionStyle = DemolitionStyle.Collapse;
                DemolishElements(command.failed_elements, command.force_multiplier);
                break;
            case "reset":
                ResetSimulation();
                break;
            case "restart_webrtc":
                RestartWebRTC();
                break;
            case "build_frame":
                if (command._rawJson != null)
                    ExecuteBuildFrame(command._rawJson);
                break;
            default:
                Debug.LogWarning($"[XuanwuAI] Unknown action: {command.action}");
                break;
        }
    }

    private void ExecuteBuildFrame(string json)
    {
        var builder = GetComponent<FrameBuilder>();
        if (builder == null)
        {
            Debug.LogWarning("[XuanwuAI] No FrameBuilder component found");
            return;
        }

        var nodes = new List<Vector3>();
        var elements = new List<(int, int, string)>();

        int nodesStart = json.IndexOf("\"nodes\"");
        int elementsStart = json.IndexOf("\"elements\"");

        if (nodesStart < 0 || elementsStart < 0) return;

        string nodesJson = json.Substring(nodesStart, elementsStart - nodesStart);
        string elementsJson = json.Substring(elementsStart);

        int idx = nodesJson.IndexOf('[');
        if (idx < 0) return;
        idx++;
        while (idx < nodesJson.Length && nodesJson[idx] != ']')
        {
            while (idx < nodesJson.Length && nodesJson[idx] != '{') idx++;
            if (idx >= nodesJson.Length || nodesJson[idx] != '{') break;
            int end = nodesJson.IndexOf('}', idx);
            if (end < 0) break;
            string nodeStr = nodesJson.Substring(idx, end - idx + 1);
            float x = ExtractFloat(nodeStr, "x");
            float y = ExtractFloat(nodeStr, "y");
            float z = ExtractFloat(nodeStr, "z");
            nodes.Add(new Vector3(x, y, z));
            idx = end + 1;
        }

        idx = elementsJson.IndexOf('[');
        if (idx < 0) return;
        idx++;
        while (idx < elementsJson.Length && elementsJson[idx] != ']')
        {
            while (idx < elementsJson.Length && elementsJson[idx] != '{') idx++;
            if (idx >= elementsJson.Length || elementsJson[idx] != '{') break;
            int end = elementsJson.IndexOf('}', idx);
            if (end < 0) break;
            string elemStr = elementsJson.Substring(idx, end - idx + 1);
            int ni = (int)ExtractFloat(elemStr, "node_i");
            int nj = (int)ExtractFloat(elemStr, "node_j");
            string type = ExtractString(elemStr, "type");
            if (string.IsNullOrEmpty(type)) type = "beam";
            elements.Add((ni, nj, type));
            idx = end + 1;
        }

        builder.BuildFrameFromData(nodes, elements);
    }

    private float ExtractFloat(string json, string key)
    {
        int keyIdx = json.IndexOf("\"" + key + "\"");
        if (keyIdx < 0) return 0f;
        int colon = json.IndexOf(':', keyIdx);
        if (colon < 0) return 0f;
        int start = colon + 1;
        while (start < json.Length && (json[start] == ' ' || json[start] == '\t')) start++;
        int end = start;
        while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '.' || json[end] == '-')) end++;
        if (end > start && float.TryParse(json.Substring(start, end - start),
            System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out float val))
            return val;
        return 0f;
    }

    private string ExtractString(string json, string key)
    {
        int keyIdx = json.IndexOf("\"" + key + "\"");
        if (keyIdx < 0) return "";
        int colon = json.IndexOf(':', keyIdx);
        if (colon < 0) return "";
        int q1 = json.IndexOf('"', colon);
        if (q1 < 0) return "";
        int q2 = json.IndexOf('"', q1 + 1);
        if (q2 < 0) return "";
        return json.Substring(q1 + 1, q2 - q1 - 1);
    }

    /// <summary>
    /// Apply explosive forces to the specified structural elements.
    /// For each failed element, incapacitate its joints and apply forces
    /// to neighboring elements to trigger cascading collapse.
    /// </summary>
    private void DemolishElements(int[] failedElementIds, float forceMultiplier)
    {
        if (forceMultiplier <= 0f) forceMultiplier = 1f;

        Debug.Log($"[XuanwuAI] Demolishing elements: [{string.Join(", ", failedElementIds)}] " +
                  $"style={demolitionStyle}, multiplier={forceMultiplier:F1}x");

        var indicesToRemove = new HashSet<int>(failedElementIds);

        if (demolitionStyle == DemolitionStyle.Collapse)
        {
            DemolishCollapse(indicesToRemove, forceMultiplier);
        }
        else
        {
            DemolishExplosive(indicesToRemove, forceMultiplier);
        }

        Debug.Log($"[XuanwuAI] Demolition executed on {failedElementIds.Length} element(s).");
    }

    private void DemolishCollapse(HashSet<int> indicesToRemove, float forceMultiplier)
    {
        for (int i = 0; i < structuralElements.Count; i++)
        {
            var element = structuralElements[i];
            if (element == null) continue;

            if (indicesToRemove.Contains(i))
            {
                var joints = element.GetComponents<Joint>();
                foreach (var joint in joints)
                    Destroy(joint);

                element.SetActive(false);
                Destroy(element, 0.5f);
            }
            else
            {
                foreach (var failId in indicesToRemove)
                {
                    if (failId >= structuralElements.Count) continue;
                    var failedElement = structuralElements[failId];
                    if (failedElement == null) continue;

                    var distance = Vector3.Distance(element.transform.position, failedElement.transform.position);
                    if (distance < explosionRadius)
                    {
                        var rb = element.GetComponent<Rigidbody>();
                        if (rb != null)
                        {
                            float aboveAmount = Mathf.Max(0, (failedElement.transform.position.y - element.transform.position.y));
                            float gravityAssist = aboveAmount > 0.1f ? 1f + aboveAmount * 0.3f : 1f;
                            rb.AddForce(Vector3.down * defaultExplosionForce * 0.03f * forceMultiplier * gravityAssist, ForceMode.Force);
                        }
                    }
                }
            }
        }
    }

    private void DemolishExplosive(HashSet<int> indicesToRemove, float forceMultiplier)
    {
        for (int i = 0; i < structuralElements.Count; i++)
        {
            var element = structuralElements[i];
            if (element == null) continue;

            var rb = element.GetComponent<Rigidbody>();

            if (indicesToRemove.Contains(i))
            {
                var joints = element.GetComponents<Joint>();
                foreach (var joint in joints)
                    Destroy(joint);

                if (rb != null)
                {
                    var direction = (element.transform.position - GetStructureCenter()).normalized;
                    if (direction.sqrMagnitude < 0.01f)
                        direction = Vector3.right + Vector3.up * 0.3f;

                    rb.AddForce(direction * defaultExplosionForce * 5f * forceMultiplier, forceMode);
                    rb.AddTorque(UnityEngine.Random.insideUnitSphere * defaultExplosionForce * 2f, forceMode);
                    rb.mass *= 0.5f;
                }
            }
            else
            {
                foreach (var failId in indicesToRemove)
                {
                    if (failId >= structuralElements.Count) continue;
                    var failedElement = structuralElements[failId];
                    if (failedElement == null) continue;

                    var distance = Vector3.Distance(element.transform.position, failedElement.transform.position);
                    if (distance < explosionRadius && rb != null)
                    {
                        var shockwaveDir = (element.transform.position - failedElement.transform.position).normalized;
                        var attenuatedForce = defaultExplosionForce * 5f * forceMultiplier *
                            (1f - distance / explosionRadius) * 0.5f;
                        rb.AddForce(shockwaveDir * attenuatedForce, forceMode);
                    }
                }
            }
        }
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
        public string style;
        public string _rawJson;
    }

    private static DemolitionCommand TryParseManually(string json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try
        {
            var cmd = new DemolitionCommand();
            cmd.force_multiplier = 1.5f;

            int idx = 0;
            while (idx < json.Length)
            {
                int keyStart = json.IndexOf('"', idx);
                if (keyStart < 0) break;
                int keyEnd = json.IndexOf('"', keyStart + 1);
                if (keyEnd < 0) break;
                string key = json.Substring(keyStart + 1, keyEnd - keyStart - 1);
                idx = keyEnd + 1;

                int colon = json.IndexOf(':', idx);
                if (colon < 0) break;
                idx = colon + 1;

                while (idx < json.Length && json[idx] == ' ') idx++;

                if (key == "action")
                {
                    if (json[idx] == '"')
                    {
                        int vEnd = json.IndexOf('"', idx + 1);
                        if (vEnd > idx) cmd.action = json.Substring(idx + 1, vEnd - idx - 1);
                        idx = vEnd + 1;
                    }
                }
                else if (key == "force_multiplier")
                {
                    int vEnd = idx;
                    while (vEnd < json.Length && (char.IsDigit(json[vEnd]) || json[vEnd] == '.' || json[vEnd] == '-')) vEnd++;
                    if (vEnd > idx) float.TryParse(json.Substring(idx, vEnd - idx), out cmd.force_multiplier);
                    idx = vEnd;
                }
                else if (key == "failed_elements")
                {
                    if (json[idx] == '[')
                    {
                        var list = new System.Collections.Generic.List<int>();
                        int arrIdx = idx + 1;
                        while (arrIdx < json.Length && json[arrIdx] != ']')
                        {
                            while (arrIdx < json.Length && (json[arrIdx] == ' ' || json[arrIdx] == ',')) arrIdx++;
                            if (arrIdx >= json.Length || json[arrIdx] == ']') break;
                            int nEnd = arrIdx;
                            while (nEnd < json.Length && char.IsDigit(json[nEnd])) nEnd++;
                            if (nEnd > arrIdx) list.Add(int.Parse(json.Substring(arrIdx, nEnd - arrIdx)));
                            arrIdx = nEnd;
                        }
                        cmd.failed_elements = list.ToArray();
                        idx = arrIdx + 1;
                    }
                }
                else idx++;
            }

            if (string.IsNullOrEmpty(cmd.action)) return null;
            return cmd;
        }
        catch { return null; }
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
