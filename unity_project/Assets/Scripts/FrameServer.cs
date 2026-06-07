using UnityEngine;
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

public class FrameServer : MonoBehaviour
{
    [Header("Server Settings")]
    [SerializeField] private int port = 5006;
    [SerializeField] private int captureFps = 3;
    [SerializeField] private int streamWidth = 480;
    [SerializeField] private int streamHeight = 270;
    [SerializeField] private int maxWsClients = 5;

    private Thread _acceptThread;
    private volatile bool _isRunning;
    private byte[] _latestFrameBmp;
    private int _frameSeq;
    private DateTime _lastCaptureTime;
    private int _captureFailCount;
    private int _totalConnections;
    private int _totalFramesSent;
    private readonly object _frameLock = new object();
    private readonly List<WebSocketClient> _wsClients = new List<WebSocketClient>();
    private readonly object _clientsLock = new object();

    class WebSocketClient
    {
        public TcpClient Tcp;
        public NetworkStream Stream;
        public volatile bool Connected = true;
        public int LastSentSeq = -1;
        public DateTime ConnectedAt = DateTime.UtcNow;
    }

    void Start()
    {
        _isRunning = true;
        _acceptThread = new Thread(AcceptLoop)
        {
            IsBackground = true,
            Name = "WSAccept"
        };
        _acceptThread.Start();
        Debug.Log($"[FrameServer] Started on port {port} ({captureFps} FPS, {streamWidth}x{streamHeight}, max {maxWsClients} WS clients)");
        InvokeRepeating(nameof(CaptureFrame), 0.5f, 1f / captureFps);
    }

    void CaptureFrame()
    {
        if (!_isRunning) return;
        var cam = Camera.main;
        if (cam == null)
        {
            if (_captureFailCount++ == 0)
                Debug.LogWarning("[FrameServer] No Camera.main found — tag a camera as MainCamera");
            return;
        }
        _captureFailCount = 0;

        int w = Mathf.Min(cam.pixelWidth, streamWidth);
        int h = Mathf.Min(cam.pixelHeight, streamHeight);
        if (w <= 0 || h <= 0) return;

        var rt = RenderTexture.GetTemporary(w, h, 24, RenderTextureFormat.ARGB32);
        var prevTarget = cam.targetTexture;
        cam.targetTexture = rt;
        cam.Render();

        var prevActive = RenderTexture.active;
        RenderTexture.active = rt;

        var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
        tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
        tex.Apply();

        cam.targetTexture = prevTarget;
        RenderTexture.active = prevActive;
        RenderTexture.ReleaseTemporary(rt);

        byte[] bmp = EncodeBmp(tex);
        Destroy(tex);

        lock (_frameLock)
        {
            _latestFrameBmp = bmp;
            _frameSeq++;
            _lastCaptureTime = DateTime.UtcNow;
        }

        lock (_clientsLock)
        {
            for (int i = _wsClients.Count - 1; i >= 0; i--)
            {
                if (!_wsClients[i].Connected) _wsClients.RemoveAt(i);
            }
        }
    }

    byte[] EncodeBmp(Texture2D tex)
    {
        int w = tex.width;
        int h = tex.height;
        int rowSize = ((w * 3 + 3) / 4) * 4;
        int pixelDataSize = rowSize * h;
        int fileSize = 14 + 40 + pixelDataSize;

        byte[] data = new byte[fileSize];
        Color32[] pixels = tex.GetPixels32();

        data[0] = (byte)'B'; data[1] = (byte)'M';
        BitConverter.GetBytes(fileSize).CopyTo(data, 2);
        BitConverter.GetBytes(54).CopyTo(data, 10);
        BitConverter.GetBytes(40).CopyTo(data, 14);
        BitConverter.GetBytes(w).CopyTo(data, 18);
        BitConverter.GetBytes(h).CopyTo(data, 22);
        BitConverter.GetBytes((short)1).CopyTo(data, 26);
        BitConverter.GetBytes((short)24).CopyTo(data, 28);
        BitConverter.GetBytes(pixelDataSize).CopyTo(data, 34);

        for (int y = 0; y < h; y++)
        {
            int rowStart = 54 + y * rowSize;
            for (int x = 0; x < w; x++)
            {
                int pi = y * w + x;
                int di = rowStart + x * 3;
                data[di] = pixels[pi].b;
                data[di + 1] = pixels[pi].g;
                data[di + 2] = pixels[pi].r;
            }
        }

        return data;
    }

    string ComputeWebSocketAccept(string key)
    {
        string magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
        using (var sha1 = SHA1.Create())
        {
            byte[] hash = sha1.ComputeHash(Encoding.ASCII.GetBytes(key + magic));
            return Convert.ToBase64String(hash);
        }
    }

    void AcceptLoop()
    {
        TcpListener listener = null;
        try
        {
            listener = new TcpListener(IPAddress.Loopback, port);
            listener.Start();
        }
        catch (Exception ex)
        {
            Debug.LogError($"[FrameServer] Failed to bind port {port}: {ex.Message}");
            return;
        }

        while (_isRunning)
        {
            TcpClient client;
            try { client = listener.AcceptTcpClient(); }
            catch (SocketException)
            {
                if (!_isRunning) break;
                Thread.Sleep(200);
                continue;
            }
            catch { break; }

            int currentCount;
            lock (_clientsLock) { currentCount = _wsClients.Count; }
            if (currentCount >= maxWsClients)
            {
                try { client.Close(); } catch { }
                continue;
            }

            _totalConnections++;
            ThreadPool.QueueUserWorkItem(HandleClient, client);
        }

        try { listener.Stop(); } catch { }
    }

    void HandleClient(object obj)
    {
        TcpClient client = (TcpClient)obj;
        try
        {
            using (client)
            using (var stream = client.GetStream())
            {
                client.ReceiveTimeout = 5000;
                byte[] buffer = new byte[8192];
                int read = stream.Read(buffer, 0, buffer.Length);
                if (read <= 0) return;

                string request = Encoding.ASCII.GetString(buffer, 0, read);

                if (request.StartsWith("GET /health"))
                {
                    ServeHealth(stream);
                }
                else if (request.Contains("Upgrade: websocket") || request.Contains("upgrade: websocket"))
                {
                    DoWebSocketUpgrade(client, stream, request);
                }
                else if (request.StartsWith("HEAD"))
                {
                    string resp = "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nAccess-Control-Allow-Origin: *\r\n\r\n";
                    stream.Write(Encoding.ASCII.GetBytes(resp), 0, resp.Length);
                }
                else if (request.StartsWith("GET"))
                {
                    ServeHttpFrame(stream);
                }
            }
        }
        catch (IOException) { }
        catch (SocketException) { }
        catch (Exception ex)
        {
            Debug.LogError("[FrameServer] Handle error: " + ex.Message);
        }
    }

    void DoWebSocketUpgrade(TcpClient client, NetworkStream stream, string request)
    {
        string key = null;
        foreach (var line in request.Split('\n'))
        {
            if (line.StartsWith("Sec-WebSocket-Key:", StringComparison.OrdinalIgnoreCase))
            {
                key = line.Substring("Sec-WebSocket-Key:".Length).Trim();
                break;
            }
        }
        if (key == null) return;

        string accept = ComputeWebSocketAccept(key);
        string response = "HTTP/1.1 101 Switching Protocols\r\n" +
                          "Upgrade: websocket\r\n" +
                          "Connection: Upgrade\r\n" +
                          "Sec-WebSocket-Accept: " + accept + "\r\n\r\n";
        stream.Write(Encoding.ASCII.GetBytes(response), 0, response.Length);

        var wsClient = new WebSocketClient { Tcp = client, Stream = stream };
        lock (_clientsLock) _wsClients.Add(wsClient);
        Debug.Log($"[FrameServer] WS client connected (total: {_wsClients.Count})");

        while (_isRunning && wsClient.Connected)
        {
            byte[] bmp = null;
            int currentSeq;
            lock (_frameLock)
            {
                bmp = _latestFrameBmp;
                currentSeq = _frameSeq;
            }

            if (bmp != null && currentSeq != wsClient.LastSentSeq)
            {
                try
                {
                    SendWsFrame(stream, bmp);
                    wsClient.LastSentSeq = currentSeq;
                    _totalFramesSent++;
                }
                catch (IOException)
                {
                    wsClient.Connected = false;
                    break;
                }
                catch (SocketException)
                {
                    wsClient.Connected = false;
                    break;
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[FrameServer] Send error: {ex.Message}");
                    wsClient.Connected = false;
                    break;
                }
            }
            Thread.Sleep(Math.Max(1, 1000 / captureFps / 2));
        }

        lock (_clientsLock) _wsClients.Remove(wsClient);
        Debug.Log($"[FrameServer] WS client disconnected (remaining: {_wsClients.Count})");
    }

    void SendWsFrame(NetworkStream stream, byte[] data)
    {
        var header = new MemoryStream();
        header.WriteByte(0x82);
        if (data.Length < 126)
        {
            header.WriteByte((byte)data.Length);
        }
        else if (data.Length <= 0xFFFF)
        {
            header.WriteByte(126);
            header.WriteByte((byte)((data.Length >> 8) & 0xFF));
            header.WriteByte((byte)(data.Length & 0xFF));
        }
        else
        {
            header.WriteByte(127);
            long len = data.Length;
            for (int i = 7; i >= 0; i--)
                header.WriteByte((byte)((len >> (i * 8)) & 0xFF));
        }

        byte[] headerBytes = header.ToArray();
        stream.Write(headerBytes, 0, headerBytes.Length);
        stream.Write(data, 0, data.Length);
        stream.Flush();
    }

    void ServeHttpFrame(NetworkStream stream)
    {
        byte[] bmp;
        lock (_frameLock) { bmp = _latestFrameBmp; }

        if (bmp != null)
        {
            string headers = "HTTP/1.1 200 OK\r\nContent-Type: image/bmp\r\nContent-Length: " + bmp.Length + "\r\n" +
                             "Cache-Control: no-cache, no-store, must-revalidate\r\nPragma: no-cache\r\nExpires: 0\r\nAccess-Control-Allow-Origin: *\r\n\r\n";
            stream.Write(Encoding.ASCII.GetBytes(headers), 0, headers.Length);
            stream.Write(bmp, 0, bmp.Length);
        }
        else
        {
            string body = "{\"status\":\"no_frame\"}";
            string resp = "HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: " + body.Length + "\r\nAccess-Control-Allow-Origin: *\r\n\r\n" + body;
            stream.Write(Encoding.ASCII.GetBytes(resp), 0, resp.Length);
        }
    }

    void ServeHealth(NetworkStream stream)
    {
        double age;
        int seq;
        int clients;
        lock (_frameLock)
        {
            age = _lastCaptureTime != default(DateTime)
                ? (DateTime.UtcNow - _lastCaptureTime).TotalSeconds
                : -1;
            seq = _frameSeq;
        }
        lock (_clientsLock) { clients = _wsClients.Count; }

        var sb = new StringBuilder();
        sb.Append("{\"status\":\"ok\"");
        sb.Append(",\"frame_seq\":").Append(seq);
        sb.Append(",\"last_capture_age_s\":").Append(age.ToString("F1"));
        sb.Append(",\"ws_clients\":").Append(clients);
        sb.Append(",\"total_connections\":").Append(_totalConnections);
        sb.Append(",\"total_frames_sent\":").Append(_totalFramesSent);
        sb.Append(",\"capture_fps\":").Append(captureFps);
        sb.Append(",\"resolution\":\"").Append(streamWidth).Append("x").Append(streamHeight).Append("\"}");
        string json = sb.ToString();

        string resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " +
                      Encoding.UTF8.GetByteCount(json) + "\r\nAccess-Control-Allow-Origin: *\r\n\r\n" + json;
        byte[] respBytes = Encoding.UTF8.GetBytes(resp);
        stream.Write(respBytes, 0, respBytes.Length);
    }

    void OnDestroy()
    {
        _isRunning = false;
        lock (_clientsLock)
        {
            foreach (var c in _wsClients)
            {
                c.Connected = false;
                try { c.Tcp.Close(); } catch { }
            }
            _wsClients.Clear();
        }
        Debug.Log($"[FrameServer] Stopped (sent {_totalFramesSent} frames, {_totalConnections} connections)");
    }
}
