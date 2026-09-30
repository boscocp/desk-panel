// The Windows half of the spectrum bars (T8.5, ADR 0021): captures what this PC
// is playing with WASAPI loopback and writes it to stdout, for
// server/spectrum.py to turn into bars. The twin of mac/spectrum_tap.swift, and
// it speaks the same protocol:
//
//   one line  "rate=<hz>\n"
//   then      mono signed 16-bit little-endian samples at that rate, for ever
//
// install_task.ps1 compiles it with the csc.exe every Windows ships in
// .NET Framework 4, which is why this is C# 5: no string interpolation, no
// expression-bodied members, no `out var`. The binary is gitignored.
//
// Written against Microsoft's documentation, checked 2026-09-30:
// - "Loopback Recording": the default *render* endpoint, a shared-mode
//   stream, AUDCLNT_STREAMFLAGS_LOOPBACK, then GetService for an
//   IAudioCaptureClient. Loopback needs no permission and no virtual device.
// - IAudioClient::Initialize: event-driven loopback works from Windows 10
//   1703; a shared event-driven stream passes 0 for both durations and sets
//   the event before Start. Before 1703 the event never fires, so every wait
//   below times out at 100 ms and the loop degrades to polling, not to a stall.
// - IAudioClient: "the first use of IAudioClient to access the audio device
//   should be on the STA thread", hence [STAThread].
// - IAudioCaptureClient::GetBuffer: one packet per call, released in full on
//   the same thread; a SILENT packet is read as zeros, whatever it points at.
// - IMMNotificationClient: the callbacks must not block and must not register
//   or unregister, so the one used here only sets a flag.
//
// When nothing plays, Windows delivers no packets and nothing is written: the
// bars fall on the phone and the server's keepalive holds the stream open.
//
// It exits when stdin reaches EOF (the server has gone), when a write fails,
// when the device is invalidated (unplugged), and when the default output
// changes. The server restarts it on the new one within seconds.
//
// **The vtables are declared in full, in header order**, checked against the
// Vtbl structs in Microsoft's windows-rs bindings (win32metadata), because the
// reference pages list methods alphabetically. COM dispatches by slot, so a
// short or reordered interface does not fail: it calls the wrong method.
// server/actions.py records the same trap for IAudioEndpointVolume.

using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int flow, int mask, out IntPtr devices);
    int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice device);
    int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
    int RegisterEndpointNotificationCallback(IMMNotificationClient client);
    int UnregisterEndpointNotificationCallback(IMMNotificationClient client);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref Guid iid, int context, IntPtr parameters,
                 [MarshalAs(UnmanagedType.IUnknown)] out object client);
    int OpenPropertyStore(int access, out IntPtr store);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetState(out int state);
}

[StructLayout(LayoutKind.Sequential)]
struct PropertyKey {
    public Guid FormatId;
    public int PropertyId;
}

// Implemented here, called by Windows: OnDeviceStateChanged, OnDeviceAdded,
// OnDeviceRemoved, OnDefaultDeviceChanged, OnPropertyValueChanged.
[ComImport, Guid("7991EEC9-7E89-4D85-8390-6C703CEC60C0"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMNotificationClient {
    [PreserveSig] int OnDeviceStateChanged([MarshalAs(UnmanagedType.LPWStr)] string id, int state);
    [PreserveSig] int OnDeviceAdded([MarshalAs(UnmanagedType.LPWStr)] string id);
    [PreserveSig] int OnDeviceRemoved([MarshalAs(UnmanagedType.LPWStr)] string id);
    [PreserveSig] int OnDefaultDeviceChanged(int flow, int role, [MarshalAs(UnmanagedType.LPWStr)] string id);
    [PreserveSig] int OnPropertyValueChanged([MarshalAs(UnmanagedType.LPWStr)] string id, PropertyKey key);
}

[Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioClient {
    int Initialize(int shareMode, int streamFlags, long bufferDuration, long periodicity,
                   IntPtr format, IntPtr sessionGuid);
    int GetBufferSize(out uint frames);
    int GetStreamLatency(out long latency);
    int GetCurrentPadding(out uint frames);
    int IsFormatSupported(int shareMode, IntPtr format, out IntPtr closest);
    int GetMixFormat(out IntPtr format);
    int GetDevicePeriod(out long defaultPeriod, out long minimumPeriod);
    int Start();
    int Stop();
    int Reset();
    int SetEventHandle(IntPtr handle);
    int GetService(ref Guid iid, [MarshalAs(UnmanagedType.IUnknown)] out object service);
}

[Guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioCaptureClient {
    int GetBuffer(out IntPtr data, out uint frames, out uint flags,
                  out ulong devicePosition, out ulong qpcPosition);
    int ReleaseBuffer(uint frames);
    int GetNextPacketSize(out uint frames);
}

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject {}

// Sets a flag and returns: the documented rules for these callbacks.
[ComVisible(true)]
class DefaultOutputWatcher : IMMNotificationClient {
    public volatile bool Changed;

    public int OnDeviceStateChanged(string id, int state) { return 0; }
    public int OnDeviceAdded(string id) { return 0; }
    public int OnDeviceRemoved(string id) { return 0; }
    public int OnPropertyValueChanged(string id, PropertyKey key) { return 0; }

    public int OnDefaultDeviceChanged(int flow, int role, string id) {
        if (flow == SpectrumTap.RENDER && role == SpectrumTap.CONSOLE) {
            Changed = true;
        }
        return 0;
    }
}

static class SpectrumTap {
    public const int RENDER = 0;          // eRender
    public const int CONSOLE = 0;         // eConsole
    const int CLSCTX_ALL = 23;
    const int SHARED = 0;                 // AUDCLNT_SHAREMODE_SHARED
    const int LOOPBACK = 0x00020000;      // AUDCLNT_STREAMFLAGS_LOOPBACK
    const int EVENTCALLBACK = 0x00040000; // AUDCLNT_STREAMFLAGS_EVENTCALLBACK
    const uint SILENT = 0x2;              // AUDCLNT_BUFFERFLAGS_SILENT
    const int WAIT_MS = 100;
    const ushort FORMAT_PCM = 1;
    const ushort FORMAT_FLOAT = 3;
    const ushort FORMAT_EXTENSIBLE = 0xFFFE;

    static Stream output;

    static void Ok(int hr, string what) {
        if (hr < 0) {
            Console.Error.WriteLine("spectrum-tap: " + what + " failed: 0x" + hr.ToString("X8"));
            Environment.Exit(1);
        }
    }

    static void Write(byte[] bytes, int count) {
        try {
            output.Write(bytes, 0, count);
            output.Flush();
        } catch (IOException) {
            Environment.Exit(0);
        }
    }

    [STAThread]
    static int Main() {
        output = Console.OpenStandardOutput();
        // Blocks until the server closes its end, however it goes.
        Thread stdinWatcher = new Thread(delegate () {
            Stream input = Console.OpenStandardInput();
            byte[] sink = new byte[64];
            try {
                while (input.Read(sink, 0, sink.Length) > 0) { }
            } catch (IOException) { }
            Environment.Exit(0);
        });
        stdinWatcher.IsBackground = true;
        stdinWatcher.Start();

        IMMDeviceEnumerator devices = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        DefaultOutputWatcher watcher = new DefaultOutputWatcher();
        Ok(devices.RegisterEndpointNotificationCallback(watcher), "RegisterEndpointNotificationCallback");

        IMMDevice device;
        Ok(devices.GetDefaultAudioEndpoint(RENDER, CONSOLE, out device), "GetDefaultAudioEndpoint");
        Guid clientIid = typeof(IAudioClient).GUID;
        object activated;
        Ok(device.Activate(ref clientIid, CLSCTX_ALL, IntPtr.Zero, out activated), "Activate");
        IAudioClient client = (IAudioClient)activated;

        IntPtr format;
        Ok(client.GetMixFormat(out format), "GetMixFormat");
        ushort tag = (ushort)Marshal.ReadInt16(format, 0);
        int channels = Marshal.ReadInt16(format, 2);
        int rate = Marshal.ReadInt32(format, 4);
        int blockAlign = Marshal.ReadInt16(format, 12);
        int bits = Marshal.ReadInt16(format, 14);
        if (tag == FORMAT_EXTENSIBLE) {
            // WAVEFORMATEXTENSIBLE: the SubFormat GUID's first four bytes are
            // the format tag it stands for (KSDATAFORMAT_SUBTYPE_PCM is 1,
            // _IEEE_FLOAT is 3), after the 18-byte header, the 2-byte samples
            // union and the 4-byte channel mask.
            tag = (ushort)Marshal.ReadInt32(format, 24);
        }
        bool isFloat = tag == FORMAT_FLOAT && bits == 32;
        bool isPcm16 = tag == FORMAT_PCM && bits == 16;
        if (!(isFloat || isPcm16) || channels <= 0) {
            Console.Error.WriteLine("spectrum-tap: unexpected mix format tag=" + tag + " bits=" + bits);
            return 1;
        }

        AutoResetEvent ready = new AutoResetEvent(false);
        Ok(client.Initialize(SHARED, LOOPBACK | EVENTCALLBACK, 0, 0, format, IntPtr.Zero), "Initialize");
        Marshal.FreeCoTaskMem(format);
        Ok(client.SetEventHandle(ready.SafeWaitHandle.DangerousGetHandle()), "SetEventHandle");
        Guid captureIid = typeof(IAudioCaptureClient).GUID;
        object service;
        Ok(client.GetService(ref captureIid, out service), "GetService");
        IAudioCaptureClient capture = (IAudioCaptureClient)service;

        int decimation = rate >= 44100 ? 2 : 1;
        byte[] header = System.Text.Encoding.ASCII.GetBytes("rate=" + (rate / decimation) + "\n");
        Write(header, header.Length);

        Ok(client.Start(), "Start");
        byte[] packet = new byte[0];
        byte[] outBytes = new byte[0];
        float carry = 0;
        int carried = 0;

        while (!watcher.Changed) {
            ready.WaitOne(WAIT_MS);
            uint pending;
            Ok(capture.GetNextPacketSize(out pending), "GetNextPacketSize");
            while (pending > 0) {
                IntPtr data;
                uint frames, flags;
                ulong devicePosition, qpcPosition;
                Ok(capture.GetBuffer(out data, out frames, out flags, out devicePosition, out qpcPosition),
                   "GetBuffer");
                int size = (int)frames * blockAlign;
                if (packet.Length < size) {
                    packet = new byte[size];
                }
                bool silent = (flags & SILENT) != 0;
                if (!silent) {
                    Marshal.Copy(data, packet, 0, size);
                }
                Ok(capture.ReleaseBuffer(frames), "ReleaseBuffer");

                int wanted = ((int)frames / decimation + 1) * 2;
                if (outBytes.Length < wanted) {
                    outBytes = new byte[wanted];
                }
                int written = 0;
                for (int frame = 0; frame < frames; frame++) {
                    float mono = 0;
                    if (!silent) {
                        int offset = frame * blockAlign;
                        for (int channel = 0; channel < channels; channel++) {
                            if (isFloat) {
                                mono += BitConverter.ToSingle(packet, offset + channel * 4);
                            } else {
                                mono += BitConverter.ToInt16(packet, offset + channel * 2) / 32768f;
                            }
                        }
                        mono /= channels;
                    }
                    carry += mono;
                    carried++;
                    if (carried == decimation) {
                        float sample = carry / decimation;
                        if (sample > 1f) { sample = 1f; }
                        if (sample < -1f) { sample = -1f; }
                        short value = (short)(sample * 32767f);
                        outBytes[written++] = (byte)(value & 0xFF);
                        outBytes[written++] = (byte)((value >> 8) & 0xFF);
                        carry = 0;
                        carried = 0;
                    }
                }
                if (written > 0) {
                    Write(outBytes, written);
                }
                Ok(capture.GetNextPacketSize(out pending), "GetNextPacketSize");
            }
        }

        // The default output moved (headphones in, say). From here, not from
        // the callback, which must not unregister; the server starts this
        // again on the new device.
        client.Stop();
        devices.UnregisterEndpointNotificationCallback(watcher);
        return 0;
    }
}
