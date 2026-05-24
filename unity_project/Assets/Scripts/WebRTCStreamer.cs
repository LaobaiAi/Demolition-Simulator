using UnityEngine;
using Unity.WebRTC;
using System;
using System.Collections;

/// <summary>
/// WebRTC streaming helper for XuanwuAI.
/// Captures a camera view, encodes it via WebRTC, and makes the stream
/// available for the frontend to consume.
///
/// Prerequisites:
///   - Install "WebRTC" package from Unity Package Manager (com.unity.webrtc)
///   - Assign a camera in the inspector (defaults to Camera.main)
///
/// The stream SDP offer can be relayed through the Gateway's signaling
/// endpoint to the frontend for peer-to-peer video playback.
/// </summary>
[RequireComponent(typeof(Camera))]
public class WebRTCStreamer : MonoBehaviour
{
    [Header("Stream Settings")]
    [SerializeField] private int streamWidth = 1280;
    [SerializeField] private int streamHeight = 720;
    [SerializeField] private int targetFrameRate = 30;
    [SerializeField] private float streamBitrate = 2000f; // kbps

    [Header("Debug")]
    [SerializeField] private bool enableDebugLog = true;

    private Camera _streamCamera;
    private RTCPeerConnection _peerConnection;
    private MediaStream _mediaStream;
    private VideoStreamTrack _videoTrack;
    private RenderTexture _renderTexture;

    public RTCPeerConnection PeerConnection => _peerConnection;
    public bool IsStreaming { get; private set; }

    public event Action<string> OnSdpOfferReady; // Base64 SDP offer

    void Start()
    {
        _streamCamera = GetComponent<Camera>();
        if (_streamCamera == null)
        {
            _streamCamera = Camera.main;
            if (_streamCamera == null)
            {
                Debug.LogError("[WebRTCStreamer] No camera found.");
                return;
            }
        }

        StartCoroutine(StartStreaming());
    }

    IEnumerator StartStreaming()
    {
        // Wait a frame for initialization
        yield return null;

        // Create RenderTexture for camera output
        _renderTexture = new RenderTexture(streamWidth, streamHeight, 24,
            RenderTextureFormat.ARGB32);
        _renderTexture.Create();
        _streamCamera.targetTexture = _renderTexture;

        // Create video track from camera
        _videoTrack = _streamCamera.CaptureStreamTrack(streamWidth, streamHeight);
        if (_videoTrack == null)
        {
            Debug.LogError("[WebRTCStreamer] Failed to create video track.");
            yield break;
        }

        // Create media stream
        _mediaStream = new MediaStream();
        _mediaStream.AddTrack(_videoTrack);

        // Create peer connection
        var config = new RTCConfiguration
        {
            iceServers = new[]
            {
                new RTCIceServer
                {
                    urls = new[] { "stun:stun.l.google.com:19302" }
                }
            }
        };
        _peerConnection = new RTCPeerConnection(ref config);

        // Add stream tracks to peer connection
        foreach (var track in _mediaStream.GetTracks())
        {
            _peerConnection.AddTrack(track, _mediaStream);
        }

        // Create SDP offer
        var op = _peerConnection.CreateOffer();
        yield return op;

        if (op.IsError)
        {
            Debug.LogError($"[WebRTCStreamer] Failed to create offer: {op.Error.message}");
            yield break;
        }

        var desc = op.Desc;
        var opSetLocal = _peerConnection.SetLocalDescription(ref desc);
        yield return opSetLocal;

        if (opSetLocal.IsError)
        {
            Debug.LogError($"[WebRTCStreamer] Failed to set local description: {opSetLocal.Error.message}");
            yield break;
        }

        IsStreaming = true;

        // Send SDP offer to the Gateway via the event
        var sdpBase64 = Convert.ToBase64String(
            System.Text.Encoding.UTF8.GetBytes(desc.sdp));
        OnSdpOfferReady?.Invoke(sdpBase64);

        if (enableDebugLog)
        {
            Debug.Log($"[WebRTCStreamer] Streaming started: {streamWidth}x{streamHeight} @{targetFrameRate}fps");
            Debug.Log($"[WebRTCStreamer] SDP Offer ready (length: {sdpBase64.Length} chars)");
        }
    }

    /// <summary>
    /// Apply a remote SDP answer received from the frontend via the Gateway.
    /// </summary>
    public IEnumerator ApplyRemoteAnswer(string base64Sdp)
    {
        var sdp = System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(base64Sdp));
        var desc = new RTCSessionDescription
        {
            type = RTCSdpType.Answer,
            sdp = sdp
        };

        var op = _peerConnection.SetRemoteDescription(ref desc);
        yield return op;

        if (op.IsError)
        {
            Debug.LogError($"[WebRTCStreamer] Failed to set remote description: {op.Error.message}");
        }
        else if (enableDebugLog)
        {
            Debug.Log("[WebRTCStreamer] Remote answer applied — WebRTC connection established.");
        }
    }

    /// <summary>
    /// Restart WebRTC streaming — stops current session and creates a new SDP offer.
    /// Call this when the gateway has lost the offer (e.g., after server restart).
    /// </summary>
    public void RestartStreaming()
    {
        StopStreaming();
        StartCoroutine(StartStreaming());
    }

    void OnDestroy()
    {
        StopStreaming();
    }

    public void StopStreaming()
    {
        IsStreaming = false;

        _videoTrack?.Dispose();
        _mediaStream?.Dispose();
        _peerConnection?.Close();
        _peerConnection?.Dispose();
        _renderTexture?.Release();

        if (_streamCamera != null)
            _streamCamera.targetTexture = null;

        if (enableDebugLog)
            Debug.Log("[WebRTCStreamer] Streaming stopped.");
    }
}
