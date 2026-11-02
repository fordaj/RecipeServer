# Speech Button

A small, reusable dictation button for text inputs and textareas using
the browser's Web Speech API.

## Files

- `assets/css/speech-button.css` --- component styles
- `assets/js/speech-button.js` --- automatic initialization and speech
  recognition
- `assets/images/microphone.svg` --- idle/recording icon
- `assets/images/checkmark.svg` --- successful completion icon
- `example.html` --- standalone demo

## Usage

1.  Copy the `assets` folder into your project.

2.  Include the stylesheet and script once:

    ```html
    <link rel="stylesheet" href="assets/css/speech-button.css" />
    <script src="assets/js/speech-button.js" defer></script>
    ```

3.  Wrap each supported `input` or `textarea` and its button in
    `.speech-input`:

    ```html
    <div class="speech-input">
      <input type="text" placeholder="Search recipes..." />
      <button
        type="button"
        class="speech-button"
        aria-label="Start dictation"
        title="Start dictation"
      >
        <span class="speech-button__icon"></span>
      </button>
    </div>
    ```

Use the same structure with a `<textarea>` instead. Add as many
`.speech-input` instances as needed; each button controls its own field.

For fields inserted dynamically after page load, call:

```javascript
window.initializeSpeechInputs();
```

Already initialized instances are skipped.

## Behavior and requirements

- Tap the microphone to start dictation; tap again to stop.
- Recognized text is inserted at the current selection/cursor
  position.
- An `input` event is dispatched so existing listeners and frameworks
  can respond.
- The checkmark appears briefly after successful recognition.
- The input is not focused when dictation starts, avoiding an
  intentional mobile-keyboard launch.
- Speech recognition support varies by browser. It generally requires
  HTTPS (or localhost), may require an internet connection, and may
  send audio to a browser/vendor speech service.
- If speech recognition is unavailable, the button is hidden.
