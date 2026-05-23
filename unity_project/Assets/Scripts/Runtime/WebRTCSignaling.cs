using UnityEngine;
using System.Collections;
using UnityEngine.Networking;
using System.Text;

/// <summary>
/// Bridges Unity WebRTC SDP offer to the Gateway's signaling endpoint.
/// Attach alongside WebRTCStreamer — listens for OnSdpOfferReady and POSTs to gateway.
/// </summary>
[RequireComponent(typeof(WebRTCStreamer))]
public class WebRTCSignaling : MonoBehaviour
{
    [Header("Gateway")]
    [SerializeField] private string gatewayUrl = "http://localhost:8000";

    [Header("Polling")]
    [SerializeField] private float answerPollInterval = 2f;
    [SerializeField] private bool autoPollAnswer = true;

    private WebRTCStreamer _streamer;
    private Coroutine _pollCoroutine;

    void Start()
    {
        _streamer = GetComponent<WebRTCStreamer>();
        _streamer.OnSdpOfferReady += OnOfferReady;
    }

    void OnDestroy()
    {
        if (_streamer != null)
            _streamer.OnSdpOfferReady -= OnOfferReady;
    }

    private void OnOfferReady(string base64Sdp)
    {
        StartCoroutine(PostOffer(base64Sdp));
    }

    IEnumerator PostOffer(string base64Sdp)
    {
        var payload = JsonUtility.ToJson(new SdpPayload { sdp = base64Sdp });
        var jsonBytes = System.Text.Encoding.UTF8.GetBytes(payload);
        using (var req = new UnityWebRequest(gatewayUrl + "/webrtc/offer", "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(jsonBytes);
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success)
                Debug.Log("[WebRTCSignaling] SDP offer posted to gateway.");
            else
                Debug.LogWarning($"[WebRTCSignaling] Failed to post offer: {req.error}");
        }

        if (autoPollAnswer && _pollCoroutine == null)
            _pollCoroutine = StartCoroutine(PollAnswer());
    }

    IEnumerator PollAnswer()
    {
        while (true)
        {
            yield return new WaitForSeconds(answerPollInterval);

            using (var req = UnityWebRequest.Get(gatewayUrl + "/webrtc/answer"))
            {
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success)
                {
                    var resp = JsonUtility.FromJson<SdpPayload>(req.downloadHandler.text);
                    if (!string.IsNullOrEmpty(resp.sdp))
                    {
                        StartCoroutine(_streamer.ApplyRemoteAnswer(resp.sdp));
                        Debug.Log("[WebRTCSignaling] Answer received and applied. WebRTC established.");
                        _pollCoroutine = null;
                        yield break;
                    }
                }
            }
        }
    }

    void OnApplicationQuit()
    {
        // Clear offer on shutdown
        StartCoroutine(ClearOffer());
    }

    IEnumerator ClearOffer()
    {
        using (var req = UnityWebRequest.Delete(gatewayUrl + "/webrtc/offer"))
        {
            yield return req.SendWebRequest();
        }
    }

    [System.Serializable]
    private class SdpPayload
    {
        public string sdp;
    }
}
