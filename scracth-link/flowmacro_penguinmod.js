(function (Scratch) {
  "use strict";

  const Cast = Scratch.Cast;

  class FlowMacroLink {
    constructor() {
      this.baseUrl = "__FLOWMACRO_BASE_URL__";
      this.sessionId = "__FLOWMACRO_SESSION_ID__";
      this.connected = false;
      this.lastError = "";
    }

    getInfo() {
      return {
        id: "flowmacrolink",
        name: "FlowMacro Link",
        color1: "#2779bd",
        color2: "#1c5d8b",
        blocks: [
          {
            blockType: Scratch.BlockType.LABEL,
            text: "Connection"
          },
          {
            opcode: "connect",
            blockType: Scratch.BlockType.COMMAND,
            text: "connect"
          },
          {
            opcode: "isConnected",
            blockType: Scratch.BlockType.BOOLEAN,
            text: "connected?"
          },
          {
            opcode: "getLastError",
            blockType: Scratch.BlockType.REPORTER,
            text: "last error"
          },
          {
            blockType: Scratch.BlockType.LABEL,
            text: "Screen"
          },
          {
            opcode: "getScreenInfo",
            blockType: Scratch.BlockType.REPORTER,
            text: "screen info"
          },
          {
            opcode: "getScreenCapture",
            blockType: Scratch.BlockType.REPORTER,
            text: "screen png uri"
          },
          {
            blockType: Scratch.BlockType.LABEL,
            text: "Mouse State"
          },
          {
            opcode: "getMouse",
            blockType: Scratch.BlockType.REPORTER,
            text: "mouse position"
          },
          {
            blockType: Scratch.BlockType.LABEL,
            text: "Mouse Actions"
          },
          {
            opcode: "moveMouseTo",
            blockType: Scratch.BlockType.COMMAND,
            text: "teleport mouse to x: [X] y: [Y] in [SECONDS] secs",
            arguments: {
              X: { type: Scratch.ArgumentType.NUMBER, defaultValue: 200 },
              Y: { type: Scratch.ArgumentType.NUMBER, defaultValue: 200 },
              SECONDS: { type: Scratch.ArgumentType.NUMBER, defaultValue: 0 }
            }
          },
          {
            opcode: "moveMouseBy",
            blockType: Scratch.BlockType.COMMAND,
            text: "move mouse by dx: [DX] dy: [DY] in [SECONDS] secs",
            arguments: {
              DX: { type: Scratch.ArgumentType.NUMBER, defaultValue: 50 },
              DY: { type: Scratch.ArgumentType.NUMBER, defaultValue: 50 },
              SECONDS: { type: Scratch.ArgumentType.NUMBER, defaultValue: 0.2 }
            }
          },
          {
            opcode: "mouseDown",
            blockType: Scratch.BlockType.COMMAND,
            text: "hold mouse [BUTTON]",
            arguments: {
              BUTTON: {
                type: Scratch.ArgumentType.STRING,
                menu: "mouseButtons"
              }
            }
          },
          {
            opcode: "mouseUp",
            blockType: Scratch.BlockType.COMMAND,
            text: "release mouse [BUTTON]",
            arguments: {
              BUTTON: {
                type: Scratch.ArgumentType.STRING,
                menu: "mouseButtons"
              }
            }
          },
          {
            opcode: "mouseClick",
            blockType: Scratch.BlockType.COMMAND,
            text: "click mouse [BUTTON] [CLICKS] times",
            arguments: {
              BUTTON: {
                type: Scratch.ArgumentType.STRING,
                menu: "mouseButtons"
              },
              CLICKS: { type: Scratch.ArgumentType.NUMBER, defaultValue: 1 }
            }
          },
          {
            blockType: Scratch.BlockType.LABEL,
            text: "Keyboard"
          },
          {
            opcode: "keyDown",
            blockType: Scratch.BlockType.COMMAND,
            text: "hold key [KEY]",
            arguments: {
              KEY: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "space"
              }
            }
          },
          {
            opcode: "keyUp",
            blockType: Scratch.BlockType.COMMAND,
            text: "release key [KEY]",
            arguments: {
              KEY: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "space"
              }
            }
          },
          {
            opcode: "keyPress",
            blockType: Scratch.BlockType.COMMAND,
            text: "press key [KEY]",
            arguments: {
              KEY: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "enter"
              }
            }
          },
          {
            opcode: "hotkey",
            blockType: Scratch.BlockType.COMMAND,
            text: "press key combo [KEYS]",
            arguments: {
              KEYS: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "ctrl,shift,esc"
              }
            }
          },
          {
            opcode: "typeText",
            blockType: Scratch.BlockType.COMMAND,
            text: "type text [TEXT]",
            arguments: {
              TEXT: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "hello"
              }
            }
          },
          {
            opcode: "waitSeconds",
            blockType: Scratch.BlockType.COMMAND,
            text: "wait on host [SECONDS] secs",
            arguments: {
              SECONDS: { type: Scratch.ArgumentType.NUMBER, defaultValue: 0.1 }
            }
          }
        ],
        menus: {
          mouseButtons: {
            acceptReporters: true,
            items: ["left", "middle", "right"]
          }
        }
      };
    }

    async request(path, options = {}) {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: options.method || "GET",
        headers: {
          "Content-Type": "application/json",
          "X-FlowMacro-Session": this.sessionId
        },
        body: options.body ? JSON.stringify(options.body) : undefined
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `HTTP ${response.status}`);
      }

      return response.json();
    }

    async connect() {
      this.lastError = "";
      try {
        await this.request("/health");
        this.connected = true;
      } catch (error) {
        this.connected = false;
        this.lastError = String(error);
      }
    }

    isConnected() {
      return this.connected;
    }

    getLastError() {
      return this.lastError;
    }

    async getScreenInfo() {
      return this.readAsJsonString("/screen/info");
    }

    async getScreenCapture() {
      try {
        const data = await this.request("/screen");
        this.connected = true;
        this.lastError = "";
        if (!data.imageBase64) {
          return "";
        }
        return `data:image/png;base64,${data.imageBase64}`;
      } catch (error) {
        this.connected = false;
        this.lastError = String(error);
        return "";
      }
    }

    async getMouse() {
      return this.readAsJsonString("/mouse");
    }

    async moveMouseTo(args) {
      await this.safeCommand("/mouse/move", {
        x: Cast.toNumber(args.X),
        y: Cast.toNumber(args.Y),
        duration: Cast.toNumber(args.SECONDS)
      });
    }

    async moveMouseBy(args) {
      await this.safeCommand("/mouse/move-by", {
        dx: Cast.toNumber(args.DX),
        dy: Cast.toNumber(args.DY),
        duration: Cast.toNumber(args.SECONDS)
      });
    }

    async mouseDown(args) {
      await this.safeCommand("/mouse/down", {
        button: String(args.BUTTON || "left").toLowerCase()
      });
    }

    async mouseUp(args) {
      await this.safeCommand("/mouse/up", {
        button: String(args.BUTTON || "left").toLowerCase()
      });
    }

    async mouseClick(args) {
      await this.safeCommand("/mouse/click", {
        button: String(args.BUTTON || "left").toLowerCase(),
        clicks: Math.max(1, Cast.toNumber(args.CLICKS))
      });
    }

    async keyDown(args) {
      await this.safeCommand("/keyboard/down", {
        key: String(args.KEY || "").trim().toLowerCase()
      });
    }

    async keyUp(args) {
      await this.safeCommand("/keyboard/up", {
        key: String(args.KEY || "").trim().toLowerCase()
      });
    }

    async keyPress(args) {
      await this.safeCommand("/keyboard/press", {
        key: String(args.KEY || "").trim().toLowerCase()
      });
    }

    async hotkey(args) {
      const keys = String(args.KEYS || "")
        .split(",")
        .map(part => part.trim().toLowerCase())
        .filter(Boolean);
      await this.safeCommand("/keyboard/hotkey", { keys });
    }

    async typeText(args) {
      await this.safeCommand("/keyboard/write", {
        text: String(args.TEXT || "")
      });
    }

    async waitSeconds(args) {
      await this.safeCommand("/wait", {
        seconds: Cast.toNumber(args.SECONDS)
      });
    }

    async readAsJsonString(path) {
      try {
        const data = await this.request(path);
        this.connected = true;
        this.lastError = "";
        return JSON.stringify(data);
      } catch (error) {
        this.connected = false;
        this.lastError = String(error);
        return "";
      }
    }

    async safeCommand(path, body) {
      try {
        await this.request(path, {
          method: "POST",
          body
        });
        this.connected = true;
        this.lastError = "";
      } catch (error) {
        this.connected = false;
        this.lastError = String(error);
      }
    }
  }

  Scratch.extensions.register(new FlowMacroLink());
})(Scratch);
