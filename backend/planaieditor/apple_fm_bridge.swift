import Dispatch
import Foundation
import FoundationModels

private func makeCString(_ string: String) -> UnsafeMutablePointer<CChar> {
    return strdup(string)!
}

private func encodeJSON(_ dict: [String: Any]) -> UnsafeMutablePointer<CChar> {
    guard let data = try? JSONSerialization.data(withJSONObject: dict, options: []),
          let text = String(data: data, encoding: .utf8)
    else {
        return makeCString("{\"ok\":false,\"error\":\"json_encode_failed\"}")
    }
    return makeCString(text)
}

@_cdecl("apple_fm_availability")
public func apple_fm_availability() -> UnsafeMutablePointer<CChar> {
    let model = SystemLanguageModel.default
    switch model.availability {
    case .available:
        return makeCString("available")
    case .unavailable(let reason):
        return makeCString("unavailable:\(reason)")
    }
}

@_cdecl("apple_fm_generate")
public func apple_fm_generate(
    _ instructionsPtr: UnsafePointer<CChar>?,
    _ promptPtr: UnsafePointer<CChar>?,
    _ temperature: Double
) -> UnsafeMutablePointer<CChar> {
    let model = SystemLanguageModel.default
    guard case .available = model.availability else {
        return encodeJSON([
            "ok": false,
            "error": "SystemLanguageModel unavailable: \(model.availability)",
        ])
    }

    let instructions = instructionsPtr.map { String(cString: $0) } ?? ""
    let prompt = promptPtr.map { String(cString: $0) } ?? ""

    let semaphore = DispatchSemaphore(value: 0)
    var payload: [String: Any] = ["ok": false, "error": "uninitialized"]

    Task {
        do {
            let session = instructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? LanguageModelSession(model: model)
                : LanguageModelSession(model: model, instructions: instructions)
            let options = GenerationOptions(temperature: temperature)
            let response = try await session.respond(to: prompt, options: options)
            payload = [
                "ok": true,
                "content": response.content,
            ]
        } catch {
            payload = [
                "ok": false,
                "error": String(describing: error),
            ]
        }
        semaphore.signal()
    }

    semaphore.wait()
    return encodeJSON(payload)
}

@_cdecl("apple_fm_free")
public func apple_fm_free(_ ptr: UnsafeMutablePointer<CChar>?) {
    if let ptr = ptr {
        free(ptr)
    }
}
