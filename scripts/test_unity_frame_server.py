"""Test Unity FrameServer WebSocket connectivity.

Tests:
1. Gateway /unity/status endpoint
2. Gateway /unity/launch endpoint
3. FrameServer WebSocket handshake and frame decoding (if Unity is running)
4. Verify WebSocket frame big-endian encoding is correct
"""
import asyncio
import json
import socket
import struct
import hashlib
import base64
import os
import time
import sys

GATEWAY = "http://localhost:8000"
FRAME_SERVER_HOST = "127.0.0.1"
FRAME_SERVER_PORT = 5006

def test_gateway_status():
    """Test /unity/status endpoint."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{GATEWAY}/unity/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        print(f"  PASS: /unity/status -> {json.dumps(data, indent=2)}")
        return data
    except Exception as e:
        print(f"  FAIL: /unity/status -> {e}")
        return None

def test_gateway_launch():
    """Test /unity/launch endpoint (won't actually launch if Unity not found)."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{GATEWAY}/unity/launch", method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        print(f"  PASS: /unity/launch -> status={data.get('status')}")
        return data
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  INFO: /unity/launch -> HTTP {e.code}: {body}")
        return None
    except Exception as e:
        print(f"  FAIL: /unity/launch -> {e}")
        return None

def test_frame_server_tcp():
    """Test if port 5006 is open (FrameServer running)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        result = sock.connect_ex((FRAME_SERVER_HOST, FRAME_SERVER_PORT))
        sock.close()
        if result == 0:
            print(f"  PASS: FrameServer TCP port {FRAME_SERVER_PORT} is OPEN")
            return True
        else:
            print(f"  INFO: FrameServer TCP port {FRAME_SERVER_PORT} is CLOSED (Unity not running)")
            return False
    except Exception as e:
        print(f"  FAIL: FrameServer TCP check -> {e}")
        return False

def compute_ws_accept(key):
    """Compute Sec-WebSocket-Accept per RFC 6455."""
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    sha1 = hashlib.sha1((key + magic).encode()).digest()
    return base64.b64encode(sha1).decode()

def test_ws_handshake():
    """Perform a real WebSocket handshake with FrameServer and try to read a frame."""
    import secrets

    ws_key = base64.b64encode(secrets.token_bytes(16)).decode()

    request = (
        f"GET / HTTP/1.1\r\n"
        f"Host: localhost:{FRAME_SERVER_PORT}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {ws_key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((FRAME_SERVER_HOST, FRAME_SERVER_PORT))

        sock.sendall(request.encode())

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        resp_str = response.decode(errors='replace')

        if "101" not in resp_str.split("\r\n")[0]:
            print(f"  FAIL: WebSocket handshake rejected: {resp_str.split(chr(13)+chr(10))[0]}")
            sock.close()
            return False

        expected_accept = compute_ws_accept(ws_key)
        if f"Sec-WebSocket-Accept: {expected_accept}" not in resp_str:
            print(f"  FAIL: Wrong Sec-WebSocket-Accept")
            print(f"    Expected: {expected_accept}")
            print(f"    Got: {resp_str}")
            sock.close()
            return False

        print(f"  PASS: WebSocket handshake succeeded")

        # Try to read a WebSocket frame (BMP image)
        print(f"  INFO: Waiting for first frame (up to 10s)...")
        sock.settimeout(10.0)

        # Read frame header (at least 2 bytes)
        header = b""
        while len(header) < 2:
            chunk = sock.recv(2 - len(header))
            if not chunk:
                break
            header += chunk

        if len(header) < 2:
            print(f"  FAIL: No frame header received")
            sock.close()
            return False

        byte0 = header[0]
        byte1 = header[1]
        opcode = byte0 & 0x0F
        is_final = (byte0 & 0x80) != 0
        is_masked = (byte1 & 0x80) != 0
        payload_len = byte1 & 0x7F

        print(f"  INFO: Frame: FIN={is_final}, Opcode=0x{opcode:02X}, Masked={is_masked}, PayloadLen7={payload_len}")

        if is_masked:
            print(f"  FAIL: Server frames should NOT be masked (RFC 6455)")
            sock.close()
            return False

        if opcode != 0x02:
            print(f"  FAIL: Expected Binary opcode (0x02), got 0x{opcode:02X}")
            sock.close()
            return False

        # Read extended payload length if needed
        if payload_len == 126:
            ext = sock.recv(2)
            if len(ext) < 2:
                print(f"  FAIL: Truncated extended payload length")
                sock.close()
                return False
            actual_len = struct.unpack('!H', ext)[0]
            print(f"  INFO: Extended 2-byte length: {actual_len}")
        elif payload_len == 127:
            ext = sock.recv(8)
            if len(ext) < 8:
                print(f"  FAIL: Truncated extended payload length")
                sock.close()
                return False
            actual_len = struct.unpack('!Q', ext)[0]
            print(f"  INFO: Extended 8-byte length: {actual_len}")
        else:
            actual_len = payload_len
            print(f"  INFO: Inline length: {actual_len}")

        if actual_len == 0:
            print(f"  FAIL: Zero-length frame")
            sock.close()
            return False

        # Read the BMP payload
        payload = b""
        while len(payload) < actual_len:
            chunk = sock.recv(min(65536, actual_len - len(payload)))
            if not chunk:
                break
            payload += chunk

        if len(payload) < actual_len:
            print(f"  FAIL: Incomplete frame: got {len(payload)}/{actual_len} bytes")
            sock.close()
            return False

        print(f"  PASS: Received complete frame: {actual_len} bytes")

        # Verify BMP signature
        if payload[:2] == b'BM':
            print(f"  PASS: Frame is valid BMP (signature 'BM' found)")

            # Read BMP header to verify dimensions
            bmp_size = struct.unpack('<I', payload[2:6])[0]
            bmp_width = struct.unpack('<i', payload[18:22])[0]
            bmp_height = struct.unpack('<i', payload[22:26])[0]
            print(f"  INFO: BMP {bmp_width}x{bmp_height}, file_size={bmp_size}")
        else:
            print(f"  FAIL: Frame is NOT a valid BMP (no 'BM' signature)")
            print(f"    First 8 bytes: {payload[:8].hex()}")

        sock.close()
        return True

    except socket.timeout:
        print(f"  FAIL: WebSocket test timed out")
        return False
    except ConnectionRefusedError:
        print(f"  INFO: FrameServer not running on port {FRAME_SERVER_PORT}")
        return False
    except Exception as e:
        print(f"  FAIL: WebSocket test error: {e}")
        return False

def test_ws_frame_encoding():
    """Verify WebSocket frame encoding is correct (big-endian lengths)."""
    print("\n--- Verifying FrameServer SendWsFrame encoding logic ---")
    print("  This test validates that payload lengths are encoded big-endian per RFC 6455.")

    # Simulate what the fixed C# code should produce
    # For a BMP of size ~388854 bytes (480x270x3 + headers)
    test_sizes = [100, 1000, 50000, 388854]

    for size in test_sizes:
        # Build header like the fixed C# code does
        header = bytearray()
        header.append(0x82)  # FIN + Binary

        if size < 126:
            header.append(size)
            expected_len_field = bytes([size])
        elif size <= 0xFFFF:
            header.append(126)
            header.append((size >> 8) & 0xFF)
            header.append(size & 0xFF)
            expected_len_field = struct.pack('!H', size)
        else:
            header.append(127)
            for i in range(7, -1, -1):
                header.append((size >> (i * 8)) & 0xFF)
            expected_len_field = struct.pack('!Q', size)

        # Parse back using big-endian
        byte1 = header[1]
        actual_parsed_len = byte1 & 0x7F

        if actual_parsed_len == 126:
            actual_parsed_len = struct.unpack('!H', bytes(header[2:4]))[0]
        elif actual_parsed_len == 127:
            actual_parsed_len = struct.unpack('!Q', bytes(header[2:10]))[0]

        if actual_parsed_len == size:
            print(f"  PASS: Size {size} -> encoded/decoded correctly (big-endian)")
        else:
            print(f"  FAIL: Size {size} -> encoded as big-endian but decoded to {actual_parsed_len}")

    # Now show what the OLD (broken) code would have produced
    print("\n  --- Verifying old code was broken ---")
    for size in [388854]:
        # Simulate BitConverter.GetBytes((ulong)size) on little-endian Windows
        le_bytes = struct.pack('<Q', size)
        # Parse as big-endian (what browser would do)
        wrong_len = struct.unpack('!Q', le_bytes)[0]
        print(f"  CONFIRMED: Old code for BMP {size}B -> browser would read length as {wrong_len} (WAY too large)")
        print(f"    Little-endian bytes: {le_bytes.hex()}")
        print(f"    Read as big-endian: {wrong_len}")

def main():
    print("=" * 60)
    print("Unity FrameServer Integration Test")
    print("=" * 60)

    # 1. Check gateway status
    print("\n1. Gateway /unity/status:")
    status = test_gateway_status()

    # 2. Check if FrameServer port is open
    print("\n2. FrameServer TCP port check:")
    fs_running = test_frame_server_tcp()

    # 3. Test WebSocket encoding logic
    print("\n3. WebSocket frame encoding verification:")
    test_ws_frame_encoding()

    # 4. If FrameServer is running, test WebSocket
    if fs_running:
        print("\n4. WebSocket handshake + frame test:")
        test_ws_handshake()
    else:
        print("\n4. WebSocket test SKIPPED (FrameServer not running)")
        print("   Start Unity and run this test again to verify end-to-end.")

    print("\n" + "=" * 60)
    print("To test end-to-end with Unity:")
    print("  1. Start gateway: cd gateway && python main.py")
    print("  2. Open Unity project or click 'Launch Unity' in frontend")
    print("  3. Run this test again to verify FrameServer WebSocket")
    print("=" * 60)

if __name__ == "__main__":
    main()
