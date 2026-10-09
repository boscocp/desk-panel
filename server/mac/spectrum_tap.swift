// The macOS half of the spectrum bars (T8.5, ADR 0021): taps what this Mac is
// playing and writes it to stdout, for server/spectrum.py to turn into bars.
//
//   swiftc -O server/mac/spectrum_tap.swift -o server/mac/spectrum-tap
//
// install_agent.sh runs that line; the binary is gitignored.
//
// It uses a Core Audio process tap (macOS 14.2+), which hands a process the
// system's output mix without a virtual device and without touching the
// routing. The tap is global and excludes nothing, and it feeds a private
// aggregate device of its own: no speaker is part of it, so switching from
// the speakers to headphones does not stop it.
//
// macOS asks once for "System Audio Recording". Until it is granted the tap
// exists and delivers nothing, which the server reports in its log.
//
// Protocol, and nothing else is ever written to stdout:
//   one line  "rate=<hz>\n"
//   then      mono signed 16-bit little-endian samples at that rate, for ever
// and, on stderr: "v=<0..100>\n" once on starting and each time the default
// output's volume changes (T8.8), the line the Windows helper writes (T8.6).
//
// The mix is downmixed and halved in rate here (48 kHz becomes 24 kHz): bars
// stop around 11 kHz, and it halves what Python has to read.
//
// It exits when stdin reaches EOF -- the server holds the other end, so the
// server going away, however it goes, takes this with it -- and when a write
// to stdout fails. The tap and the aggregate are private to this process and
// die with it.

import AudioToolbox
import CoreAudio
import Foundation

func fail(_ what: String, _ status: OSStatus) -> Never {
    FileHandle.standardError.write("spectrum-tap: \(what) failed: \(status)\n".data(using: .utf8)!)
    exit(1)
}

let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
description.isPrivate = true
description.muteBehavior = .unmuted

var tap = AudioObjectID(kAudioObjectUnknown)
var status = AudioHardwareCreateProcessTap(description, &tap)
if status != noErr { fail("AudioHardwareCreateProcessTap", status) }

var formatAddress = AudioObjectPropertyAddress(
    mSelector: kAudioTapPropertyFormat,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain)
var format = AudioStreamBasicDescription()
var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
status = AudioObjectGetPropertyData(tap, &formatAddress, 0, nil, &size, &format)
if status != noErr { fail("reading the tap format", status) }

// The tap delivers interleaved Float32; anything else is a macOS this was not
// measured on, and garbage bars are worse than none.
let isFloat = format.mFormatFlags & kAudioFormatFlagIsFloat != 0
let interleaved = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved == 0
guard isFloat, interleaved, format.mBitsPerChannel == 32, format.mChannelsPerFrame > 0 else {
    FileHandle.standardError.write("spectrum-tap: unexpected tap format \(format)\n".data(using: .utf8)!)
    exit(1)
}
let channels = Int(format.mChannelsPerFrame)
let decimation = format.mSampleRate >= 44100 ? 2 : 1
let outputRate = Int(format.mSampleRate) / decimation

let aggregate: [String: Any] = [
    kAudioAggregateDeviceNameKey: "desk-panel spectrum",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceTapListKey: [[
        kAudioSubTapDriftCompensationKey: true,
        kAudioSubTapUIDKey: description.uuid.uuidString,
    ]],
]
var device = AudioObjectID(kAudioObjectUnknown)
status = AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &device)
if status != noErr { fail("AudioHardwareCreateAggregateDevice", status) }

let stdout = FileHandle.standardOutput
stdout.write("rate=\(outputRate)\n".data(using: .utf8)!)

// SIGPIPE would kill the process mid-write with no word; ignoring it turns a
// closed pipe into a write error, handled below as an exit.
signal(SIGPIPE, SIG_IGN)

// A serial queue rather than the real-time I/O thread: the block writes to a
// pipe, which may block, and blocking the I/O thread is what glitches audio.
let queue = DispatchQueue(label: "spectrum-tap")
var carry: Float = 0
var carried = 0
var procID: AudioDeviceIOProcID?
status = AudioDeviceCreateIOProcIDWithBlock(&procID, device, queue) { _, input, _, _, _ in
    let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
    var out = [Int16]()
    for buffer in buffers {
        guard let data = buffer.mData?.assumingMemoryBound(to: Float.self) else { continue }
        let frames = Int(buffer.mDataByteSize) / (4 * channels)
        out.reserveCapacity(out.count + frames / decimation + 1)
        for frame in 0..<frames {
            var mono: Float = 0
            for channel in 0..<channels { mono += data[frame * channels + channel] }
            carry += mono / Float(channels)
            carried += 1
            if carried == decimation {
                let sample = max(-1, min(1, carry / Float(decimation)))
                out.append(Int16(sample * 32767).littleEndian)
                carry = 0
                carried = 0
            }
        }
    }
    if out.isEmpty { return }
    let bytes = out.withUnsafeBufferPointer { Data(buffer: $0) }
    do {
        try stdout.write(contentsOf: bytes)
    } catch {
        exit(0)
    }
}
if status != noErr { fail("AudioDeviceCreateIOProcIDWithBlock", status) }
status = AudioDeviceStart(device, procID)
if status != noErr { fail("AudioDeviceStart", status) }

// The output volume (T8.8), the number `osascript -e "output volume of (get
// volume settings)"` gives /quotes: the default output's virtual main volume,
// as a whole percent. Core Audio calls back when it moves and when the
// default output changes, so nothing here polls. A device with no such
// control (some HDMI and USB outputs) sends no line, and the bar keeps the
// level /quotes reads.
let volumeQueue = DispatchQueue(label: "spectrum-tap.volume")
var defaultOutputAddress = AudioObjectPropertyAddress(
    mSelector: kAudioHardwarePropertyDefaultOutputDevice,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain)
var mainVolumeAddress = AudioObjectPropertyAddress(
    mSelector: kAudioHardwareServiceDeviceProperty_VirtualMainVolume,
    mScope: kAudioDevicePropertyScopeOutput,
    mElement: kAudioObjectPropertyElementMain)
var output = AudioObjectID(kAudioObjectUnknown)
var listening = Set<AudioObjectID>()
var lastVolume = -1

func reportVolume() {
    var scalar: Float32 = 0
    var size = UInt32(MemoryLayout<Float32>.size)
    guard output != kAudioObjectUnknown,
          AudioObjectGetPropertyData(output, &mainVolumeAddress, 0, nil, &size, &scalar) == noErr
    else { return }
    let level = max(0, min(100, Int((scalar * 100).rounded())))
    if level == lastVolume { return }
    lastVolume = level
    FileHandle.standardError.write("v=\(level)\n".data(using: .utf8)!)
}

// Listeners are added once per device and never removed: a device left behind
// still calls, and reportVolume reads only the current output, so the call is
// a read that changes nothing.
func followDefaultOutput() {
    var device = AudioObjectID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
                                     &defaultOutputAddress, 0, nil, &size, &device) == noErr
    else { return }
    output = device
    if !listening.contains(device),
       AudioObjectAddPropertyListenerBlock(device, &mainVolumeAddress, volumeQueue,
                                           { _, _ in reportVolume() }) == noErr {
        listening.insert(device)
    }
    reportVolume()
}

AudioObjectAddPropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject),
                                    &defaultOutputAddress, volumeQueue,
                                    { _, _ in followDefaultOutput() })
volumeQueue.async { followDefaultOutput() }

// Blocks until the server closes its end of stdin, or dies.
_ = FileHandle.standardInput.readDataToEndOfFile()
AudioDeviceStop(device, procID)
exit(0)
