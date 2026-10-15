# Interact with GUI

This subfolder provides the GUI mode of `pdf2zh`.

## Usage

1. Run `pdf2zh -i`

2. Drop the PDF file into the window and click `Translate`.

### Configuring a service's API URL and model

Pick a service from the **Service** dropdown; one editable field appears per setting it needs (`*_BASE_URL`, `*_API_KEY`, `*_MODEL`, ...). Fill in the base URL to use your own relay, proxy, or a local OpenAI-compatible server, and set the model name you want.

Every OpenAI-compatible service now exposes its endpoint, including the ones whose URL used to be fixed in code (DeepSeek, Zhipu, SiliconFlow, 302.AI, Gemini, Groq, MiniMax, ModelScope, Qwen-MT). Leave the URL field empty to keep the service's default endpoint. See [Advanced Usage](ADVANCED.md#cofig) for the field names and their defaults.

### Environment Variables

You can set the source and target languages using environment variables:

- `PDF2ZH_LANG_FROM`: Sets the source language. Defaults to "English".
- `PDF2ZH_LANG_TO`: Sets the target language. Defaults to "Simplified Chinese".

### Supported Languages

The following languages are supported:

- English
- Simplified Chinese
- Traditional Chinese
- French
- German
- Japanese
- Korean
- Russian
- Spanish
- Italian

## Preview

<img src="./images/before.png" width="500"/>
<img src="./images/after.png" width="500"/>

## Maintainance

GUI maintained by [Rongxin](https://github.com/reycn)
