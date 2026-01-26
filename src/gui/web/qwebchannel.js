"use strict";

var QWebChannelMessageTypes = {
    signal: 1,
    propertyUpdate: 2,
    init: 3,
    idle: 4,
    debug: 5,
    invokeMethod: 6,
    connectToSignal: 7,
    disconnectFromSignal: 8,
    setProperty: 9,
    response: 10,
};

var QWebChannel = function (transport, initCallback) {
    if (typeof transport !== "object" || typeof transport.send !== "function") {
        console.error("The QWebChannel expects a transport object with a send function and onmessage callback property." +
            " Given is: transport: " + typeof (transport) + ", transport.send: " + typeof (transport.send));
        return;
    }

    var channel = this;
    this.transport = transport;

    this.send = function (data) {
        if (typeof (data) !== "string") {
            data = JSON.stringify(data);
        }
        channel.transport.send(data);
    }

    this.execCallbacks = {};
    this.execId = 0;
    this.exec_callbacks = {}; // deprecated
    this.objects = {};

    this.handleSignal = function (message) {
        var object = channel.objects[message.object];
        if (object) {
            object.signalEmitted(message.signal, message.args);
        } else {
            console.warn("Unhandled signal: " + message.object + "::" + message.signal);
        }
    }

    this.handleResponse = function (message) {
        if (!message.hasOwnProperty("id")) {
            console.error("Invalid response message received: ", message);
            return;
        }
        channel.execCallbacks[message.id](message.data);
        delete channel.execCallbacks[message.id];
    }

    this.handlePropertyUpdate = function (message) {
        for (var i in message.data) {
            var data = message.data[i];
            var object = channel.objects[data.object];
            if (object) {
                object.propertyUpdate(data.signals, data.properties);
            } else {
                console.warn("Unhandled property update: " + data.object + "::" + data.signal);
            }
        }
        channel.execCallbacks[message.id](message.data);
        delete channel.execCallbacks[message.id];
    }

    this.debug = function (message) {
        channel.send({ type: QWebChannelMessageTypes.debug, data: message });
    }

    this.transport.onmessage = function (message) {
        var data = message.data;
        if (typeof data === "string") {
            data = JSON.parse(data);
        }
        switch (data.type) {
            case QWebChannelMessageTypes.signal:
                channel.handleSignal(data);
                break;
            case QWebChannelMessageTypes.response:
                channel.handleResponse(data);
                break;
            case QWebChannelMessageTypes.propertyUpdate:
                channel.handlePropertyUpdate(data);
                break;
            default:
                console.error("Invalid message received: ", data);
                break;
        }
    }

    this.exec = function (data, callback) {
        if (!callback) {
            // if no callback is given, send the message directly
            channel.send(data);
            return;
        }
        if (channel.execId === Number.MAX_VALUE) {
            // wrap
            channel.execId = 0;
        }
        data.id = channel.execId;
        channel.execCallbacks[channel.execId] = callback;
        channel.execId++;
        channel.send(data);
    }

    this.objects = {};

    this.handleInit = function (data) {
        channel.objects = {};
        for (var k in data) {
            var objectName = k;
            var objectInfo = data[k];
            var object = new QObject(objectName, objectInfo, channel);
            channel.objects[objectName] = object;
        }
        if (initCallback) {
            initCallback(channel);
        }
    }

    this.handleSignal = function (message) {
        var object = channel.objects[message.object];
        if (object) {
            object.signalEmitted(message.signal, message.args);
        } else {
            console.warn("Unhandled signal: " + message.object + "::" + message.signal);
        }
    }

    this.handleResponse = function (message) {
        if (!message.hasOwnProperty("id")) {
            console.error("Invalid response message received: ", message);
            return;
        }
        channel.execCallbacks[message.id](message.data);
        delete channel.execCallbacks[message.id];
    }

    this.handlePropertyUpdate = function (message) {
        for (var i in message.data) {
            var data = message.data[i];
            var object = channel.objects[data.object];
            if (object) {
                object.propertyUpdate(data.signals, data.properties);
            } else {
                console.warn("Unhandled property update: " + data.object + "::" + data.signal);
            }
        }
        channel.execCallbacks[message.id](message.data);
        delete channel.execCallbacks[message.id];
    }

    this.transport.onmessage = function (message) {
        var data = message.data;
        if (typeof data === "string") {
            data = JSON.parse(data);
        }
        switch (data.type) {
            case QWebChannelMessageTypes.signal:
                channel.handleSignal(data);
                break;
            case QWebChannelMessageTypes.response:
                channel.handleResponse(data);
                break;
            case QWebChannelMessageTypes.propertyUpdate:
                channel.handlePropertyUpdate(data);
                break;
            case QWebChannelMessageTypes.init:
                channel.handleInit(data);
                break;
            case QWebChannelMessageTypes.idle:
            case QWebChannelMessageTypes.debug:
            case QWebChannelMessageTypes.invokeMethod:
            case QWebChannelMessageTypes.connectToSignal:
            case QWebChannelMessageTypes.disconnectFromSignal:
            case QWebChannelMessageTypes.setProperty:
                break;
            default:
                console.error("Invalid message received: ", data);
                break;
        }
    }

    channel.exec({ type: QWebChannelMessageTypes.init }, function (data) {
        channel.handleInit(data);
    });
};

function QObject(name, data, webChannel) {
    this.__id__ = name;
    this.webChannel = webChannel;

    for (var i in data.methods) {
        var method = data.methods[i];
        this[method[0]] = this.__createMethod(method[0], method[1]);
    }

    for (var i in data.properties) {
        var property = data.properties[i];
        this[property[0]] = property[1];
        this.__createProperty(property[0], property[1], property[2]);
    }

    for (var i in data.signals) {
        var signal = data.signals[i];
        this[signal[0]] = this.__createSignal(signal[0], signal[1]);
    }
}

QObject.prototype.__createMethod = function (methodName, args) {
    var object = this;
    return function () {
        var callArgs = [];
        for (var i = 0; i < arguments.length; i++) {
            callArgs.push(arguments[i]);
        }
        var callback = undefined;
        if (callArgs.length > 0 && typeof callArgs[callArgs.length - 1] === "function") {
            callback = callArgs.pop();
        }

        object.webChannel.exec({
            "type": QWebChannelMessageTypes.invokeMethod,
            "object": object.__id__,
            "method": methodName,
            "args": callArgs
        }, function (response) {
            if (response !== undefined) {
                var result = response;
                if (callback) {
                    callback(result);
                }
            }
        });
    };
};

QObject.prototype.__createProperty = function (name, value, signals) {
    var object = this;
    Object.defineProperty(object, name, {
        configurable: true,
        get: function () {
            return value;
        },
        set: function (newValue) {
            value = newValue;
            signals.forEach(function (signal) {
                object[signal](object.__id__, newValue);
            });
            object.webChannel.exec({
                "type": QWebChannelMessageTypes.setProperty,
                "object": object.__id__,
                "property": name,
                "value": newValue
            });
        }
    });

    object.propertyUpdate = function (signals, properties) {
        for (var i in properties) {
            var property = properties[i];
            // update internal value
            value = property[1];
        }
    };
};

QObject.prototype.__createSignal = function (name, args) {
    var object = this;
    var signal = function () {
        var listenerArgs = [];
        for (var i = 0; i < arguments.length; i++) {
            listenerArgs.push(arguments[i]);
        }
        signal.listeners.forEach(function (listener) {
            listener.apply(listener, listenerArgs);
        });
    };
    signal.listeners = [];
    signal.connect = function (callback) {
        signal.listeners.push(callback);
        object.webChannel.exec({
            "type": QWebChannelMessageTypes.connectToSignal,
            "object": object.__id__,
            "signal": name
        });
    };
    signal.disconnect = function (callback) {
        var idx = signal.listeners.indexOf(callback);
        if (idx !== -1) {
            signal.listeners.splice(idx, 1);
            object.webChannel.exec({
                "type": QWebChannelMessageTypes.disconnectFromSignal,
                "object": object.__id__,
                "signal": name
            });
        }
    };
    return signal;
};

QObject.prototype.signalEmitted = function (signalName, signalArgs) {
    var signal = this[signalName];
    if (signal) {
        signal.listeners.forEach(function (listener) {
            listener.apply(listener, signalArgs);
        });
    }
};
