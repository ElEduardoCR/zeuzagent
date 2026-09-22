import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    width: 1100
    height: 720
    minimumWidth: 820
    minimumHeight: 600
    visible: true
    property bool darkAppearance: Qt.styleHints.colorScheme === Qt.Dark
    color: darkAppearance ? "#101A24" : "#F5F9FC"
    title: "Zeuz Agent"

    property color surface: darkAppearance ? "#182633" : "#FFFFFF"
    property color raised: darkAppearance ? "#213544" : "#EDF7FD"
    property color border: darkAppearance ? "#496073" : "#CFE1EC"
    property color primary: darkAppearance ? "#76CEF2" : "#0C729E"
    property color primaryDark: darkAppearance ? "#B9DEFA" : "#0B2748"
    property color textMain: darkAppearance ? "#F0F6FA" : "#102A43"
    property color textMuted: darkAppearance ? "#B4C7D7" : "#536B7E"
    property color success: darkAppearance ? "#74D8B3" : "#147A5B"
    property color warning: darkAppearance ? "#FFD18A" : "#955B0A"
    property color danger: darkAppearance ? "#FF9FAB" : "#B4233A"
    property color skySoft: darkAppearance ? "#213C50" : "#DDF2FC"
    property color dangerSoft: darkAppearance ? "#462834" : "#FDECEF"
    property color disabledSurface: darkAppearance ? "#253441" : "#E8EFF4"
    property color disabledText: darkAppearance ? "#93A7B7" : "#7D8E9D"
    property string editingMachineId: ""
    property var editingRevision: 0
    property var renamingDevice: ({})

    palette.window: color
    palette.windowText: textMain
    palette.base: surface
    palette.alternateBase: raised
    palette.text: textMain
    palette.button: surface
    palette.buttonText: textMain
    palette.highlight: primary
    palette.highlightedText: surface
    palette.placeholderText: textMuted

    function editMachine(machine) {
        backend.beginMachineEdit()
        editingRevision = machine && machine.revision ? machine.revision : 0
        editingMachineId = machine && machine.id ? machine.id : ""
        machineNameField.text = machine && machine.name ? machine.name : ""
        machineHostField.text = machine && machine.dnc_host ? machine.dnc_host : ""
        machinePortField.value = machine && machine.dnc_port ? machine.dnc_port : 5000
        baudField.value = machine && machine.baudrate ? machine.baudrate : 9600
        dataBitsBox.currentIndex = Math.max(0, [5, 6, 7, 8].indexOf(machine && machine.bytesize ? machine.bytesize : 8))
        parityBox.currentIndex = Math.max(0, ["N", "E", "O", "M", "S"].indexOf(machine && machine.parity ? machine.parity : "N"))
        stopBitsBox.currentIndex = (machine && machine.stopbits === 2) ? 1 : 0
        flowBox.currentIndex = Math.max(0, ["xonxoff", "rtscts", "none"].indexOf(machine && machine.flow_control ? machine.flow_control : "xonxoff"))
        terminatorBox.currentIndex = Math.max(0, ["CR", "CRLF", "LF"].indexOf(machine && machine.line_terminator ? machine.line_terminator : "CRLF"))
        dtrCheck.checked = machine && machine.dtr ? true : false
        rtsCheck.checked = machine && machine.rts ? true : false
        dripCheck.checked = machine && machine.dripfeed ? true : false
        machineDialog.open()
    }

    function saveMachine() {
        var saved = backend.saveMachine({
            "id": editingMachineId,
            "revision": editingRevision,
            "name": machineNameField.text,
            "dnc_host": machineHostField.text,
            "dnc_port": machinePortField.value,
            "baudrate": baudField.value,
            "bytesize": [5, 6, 7, 8][dataBitsBox.currentIndex],
            "parity": ["N", "E", "O", "M", "S"][parityBox.currentIndex],
            "stopbits": [1, 2][stopBitsBox.currentIndex],
            "flow_control": ["xonxoff", "rtscts", "none"][flowBox.currentIndex],
            "line_terminator": ["CR", "CRLF", "LF"][terminatorBox.currentIndex],
            "dtr": dtrCheck.checked,
            "rts": rtsCheck.checked,
            "dripfeed": dripCheck.checked
        })
        if (saved) machineDialog.close()
    }

    onClosing: function(close) {
        if (backend.trayAvailable && !backend.quitting) {
            close.accepted = false
            window.hide()
            backend.notifyStillRunning()
        }
    }

    component Card: Rectangle {
        radius: 16
        color: window.surface
        border.color: window.border
        border.width: 1
    }

    component ZeuzButton: Button {
        id: control
        property color buttonColor: window.primaryDark
        property color labelColor: window.surface
        property color borderColor: buttonColor
        property int buttonRadius: 10
        implicitHeight: 44
        leftPadding: 18
        rightPadding: 18
        font.pixelSize: 14
        font.weight: Font.DemiBold
        background: Rectangle {
            radius: control.buttonRadius
            color: !control.enabled ? window.disabledSurface
                  : control.down ? Qt.darker(control.buttonColor, 1.18)
                  : control.hovered ? Qt.lighter(control.buttonColor, 1.08)
                  : control.buttonColor
            border.color: control.enabled ? control.borderColor : window.border
            border.width: control.activeFocus ? 3 : 1
        }
        contentItem: Text {
            text: control.text
            color: control.enabled ? control.labelColor : window.disabledText
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    component TextButton: Button {
        id: control
        property color labelColor: window.primary
        property color hoverColor: window.skySoft
        implicitHeight: 36
        leftPadding: 12
        rightPadding: 12
        font.pixelSize: 13
        font.weight: Font.DemiBold
        background: Rectangle {
            radius: 9
            color: control.down ? Qt.darker(control.hoverColor, 1.06)
                  : control.hovered ? control.hoverColor
                  : "transparent"
            border.width: control.activeFocus ? 2 : 0
            border.color: window.primary
        }
        contentItem: Text {
            text: control.text
            color: control.enabled ? control.labelColor : window.disabledText
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    component SectionTitle: Text {
        color: window.primaryDark
        font.pixelSize: 12
        font.weight: Font.Bold
        font.letterSpacing: 1.2
    }

    header: Rectangle {
        height: 76
        color: window.surface
        border.color: window.border
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 26
            anchors.rightMargin: 26
            spacing: 16

            ColumnLayout {
                spacing: 1
                Image {
                    source: window.darkAppearance ? "../assets/agent-dark.svg" : "../assets/agent-light.svg"
                    Layout.preferredWidth: 210
                    Layout.preferredHeight: 42
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignLeft
                    Accessible.name: "ZEUZ Agent"
                    Accessible.role: Accessible.StaticText
                }
                Text {
                    text: "Puente local de programas CNC"
                    color: textMuted
                    font.pixelSize: 12
                }
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                Layout.preferredWidth: statusRow.implicitWidth + 24
                Layout.preferredHeight: 38
                radius: 19
                color: backend.error ? dangerSoft : raised
                border.color: window.border
                Row {
                    id: statusRow
                    anchors.centerIn: parent
                    spacing: 8
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 9
                        height: 9
                        radius: 5
                        color: backend.running ? success : backend.error ? danger : textMuted
                    }
                    Text {
                        text: backend.status.toUpperCase()
                        color: backend.running ? success : backend.error ? danger : textMuted
                        font.pixelSize: 12
                        font.weight: Font.Bold
                    }
                }
            }

            ZeuzButton {
                text: backend.running ? "DETENER" : "INICIAR"
                buttonColor: backend.running ? dangerSoft : primaryDark
                borderColor: backend.running ? "#F3C5CD" : primaryDark
                labelColor: backend.running ? danger : surface
                onClicked: backend.running ? backend.stop() : backend.start()
            }

            TextButton {
                text: "Salir"
                labelColor: textMuted
                onClicked: backend.quitApplication()
            }
        }
    }

    ScrollView {
        objectName: "workshopScroll"
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 16

            Item { Layout.preferredHeight: 4 }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                spacing: 16

                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 220

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10

                        SectionTitle { text: "EMPAREJAMIENTO" }
                        Text {
                            text: backend.pairingCode
                            color: textMain
                            font.pixelSize: 42
                            font.weight: Font.Black
                            font.letterSpacing: 7
                        }
                        Text {
                            text: "Introduce este código en ZeuzDNC para autorizar el dispositivo."
                            color: textMuted
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        Item { Layout.fillHeight: true }
                        RowLayout {
                            Layout.fillWidth: true
                            ZeuzButton {
                                text: "COPIAR CÓDIGO"
                                onClicked: backend.copyText(backend.pairingCode.replace(" ", ""))
                            }
                            ZeuzButton {
                                text: "GENERAR OTRO"
                                buttonColor: raised
                                labelColor: textMain
                                borderColor: border
                                onClicked: backend.regeneratePairingCode()
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 220

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10

                        SectionTitle { text: "DIRECCIÓN DEL AGENTE" }
                        Repeater {
                            model: backend.addresses
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 48
                                radius: 11
                                color: raised
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 8
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.url
                                        color: textMain
                                        font.family: "Consolas"
                                        font.pixelSize: 14
                                        elide: Text.ElideRight
                                    }
                                    TextButton {
                                        text: "Copiar"
                                        onClicked: backend.copyText(modelData.url)
                                    }
                                }
                            }
                        }
                        Text {
                            text: backend.discoveryStatus
                            color: backend.running ? success : textMuted
                            font.pixelSize: 13
                        }
                        Text {
                            visible: backend.error.length > 0
                            text: backend.error
                            color: danger
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.preferredHeight: 288

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 10

                    SectionTitle { text: "PROGRAMAS · COMPUTADORA → SERVIDOR DEL TALLER" }
                    RowLayout {
                        Layout.fillWidth: true
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            radius: 11
                            color: raised
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                verticalAlignment: Text.AlignVCenter
                                text: backend.programsDir
                                color: textMain
                                font.pixelSize: 14
                                elide: Text.ElideMiddle
                            }
                        }
                        ZeuzButton {
                            text: "ABRIR"
                            buttonColor: raised
                            labelColor: textMain
                            borderColor: border
                            onClicked: backend.openProgramsDirectory()
                        }
                        ZeuzButton {
                            text: "CAMBIAR"
                            onClicked: backend.selectProgramsDirectory()
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TextField {
                            id: programServerHost
                            Layout.fillWidth: true
                            placeholderText: "Servidor · zeuz-dnc-xxxx.local"
                            text: backend.programServer
                            Accessible.name: "Dirección del servidor de programas"
                        }
                        SpinBox { id: programServerPort; from: 1; to: 65535; value: backend.programServerPort; editable: true; Accessible.name: "Puerto del servidor" }
                        ZeuzButton { text: "Elegir servidor"; onClicked: backend.selectProgramServer(programServerHost.text, programServerPort.value) }
                        TextButton { text: "Sincronizar"; enabled: backend.running; onClicked: backend.syncNow() }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: backend.syncStatus
                        color: textMain
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Se copian archivos nuevos y actualizados. Los borrados se conservan en la Pi; las versiones reemplazadas quedan respaldadas."
                        color: textMuted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.preferredHeight: 480

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 18

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                SectionTitle { text: "MÁQUINAS DEL TALLER" }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Perfiles compartidos con iPhone y la pantalla táctil."
                                    color: textMuted
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                            }
                            ZeuzButton {
                                text: "+ AGREGAR"
                                onClicked: editMachine(null)
                            }
                        }

                        ListView {
                            id: machineList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 7
                            model: backend.machines
                            delegate: Rectangle {
                                required property var modelData
                                width: machineList.width
                                height: 58
                                radius: 11
                                color: raised
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 10
                                    spacing: 8
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.name
                                            color: textMain
                                            font.pixelSize: 14
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.dnc_host + " · " + modelData.baudrate + " " + modelData.bytesize + modelData.parity + modelData.stopbits
                                            color: textMuted
                                            font.pixelSize: 11
                                            elide: Text.ElideRight
                                        }
                                    }
                                    ZeuzButton {
                                        Layout.preferredWidth: 76
                                        implicitHeight: 36
                                        leftPadding: 10
                                        rightPadding: 10
                                        text: "EDITAR"
                                        buttonColor: skySoft
                                        borderColor: "#A9D9EE"
                                        labelColor: primaryDark
                                        onClicked: editMachine(modelData)
                                    }
                                    ZeuzButton {
                                        Layout.preferredWidth: 88
                                        implicitHeight: 36
                                        leftPadding: 10
                                        rightPadding: 10
                                        text: "ELIMINAR"
                                        buttonColor: dangerSoft
                                        borderColor: "#F3C5CD"
                                        labelColor: danger
                                        onClicked: backend.deleteMachine(modelData.id)
                                    }
                                }
                            }
                        }
                        Text {
                            visible: backend.machines.length === 0
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: "Aún no hay máquinas. Busca una Orange Pi o agrega la primera CNC."
                            color: textMuted
                            font.pixelSize: 13
                        }
                    }

                    Rectangle {
                        Layout.preferredWidth: 340
                        Layout.fillHeight: true
                        radius: 14
                        color: window.surface
                        border.color: window.border
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 9
                            SectionTitle { text: "DISPOSITIVOS ZEUZ" }
                            Text {
                                text: "Detecta equipos Zeuz cercanos y asígnalos a una máquina sin escribir direcciones."
                                color: textMuted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            ZeuzButton {
                                Layout.fillWidth: true
                                text: backend.discovering ? "Buscando…" : "Actualizar dispositivos"
                                enabled: !backend.discovering
                                onClicked: backend.discoverDevices()
                            }
                            ListView {
                                id: deviceList
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 6
                                model: backend.discoveredDevices
                                delegate: Rectangle {
                                    required property var modelData
                                    width: deviceList.width
                                    height: 270
                                    radius: 9
                                    color: raised
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 2
                                        Text { text: modelData.name; color: textMain; font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                        Text { text: modelData.host + " · " + (modelData.status || "Detectado"); color: textMuted; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
                                        RowLayout {
                                            TextButton { text: "Renombrar"; onClicked: { renamingDevice = modelData; deviceNameField.text = modelData.name; deviceNameDialog.open() } }
                                            TextButton { text: "Usar servidor"; onClicked: backend.selectProgramServer(modelData.host, modelData.port) }
                                        }
                                        RowLayout {
                                            TextButton { text: "Importar perfiles"; onClicked: backend.importMachines(modelData.host, modelData.port) }
                                            TextButton { text: "Asignar CNC"; onClicked: editMachine({"name": modelData.name, "dnc_host": modelData.host, "dnc_port": modelData.port}) }
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            color: modelData.update && modelData.update.available ? primary : textMuted
                                            font.pixelSize: 12
                                            wrapMode: Text.Wrap
                                            text: {
                                                if (!(modelData.capabilities && modelData.capabilities.remote_update)) return "Firmware " + (modelData.version || "anterior") + " · requiere instalación inicial para actualizar a distancia"
                                                var u = modelData.update || {}
                                                var labels = {checking: "Buscando actualizaciones…", available: "Actualización disponible", waiting_idle: "Esperando a que termine el envío", downloading: "Descargando…", installing: "Instalando…", restarting: "Reconectando…", succeeded: "Actualización completada", rolled_back: "Se restauró la versión anterior", failed: "Actualización fallida", idle: "Al día"}
                                                return (labels[u.phase] || "Comprobando") + (u.phase === "downloading" && u.downloaded_bytes ? " · " + (u.downloaded_bytes / 1048576).toFixed(1) + " MB" : "") + (u.latest_version && u.available ? " · " + u.latest_version : "") + (u.error ? " · " + u.error : "") + (u.connection_error ? " · " + u.connection_error : "")
                                            }
                                        }
                                        RowLayout {
                                            visible: !!(modelData.capabilities && modelData.capabilities.remote_update)
                                            TextButton { text: "Vincular"; visible: !(modelData.update && modelData.update.supported); onClicked: backend.pairUpdateDevice(modelData.host, modelData.port) }
                                            TextButton { text: "Comprobar"; enabled: !!(modelData.online && modelData.update && modelData.update.supported); onClicked: backend.checkDeviceUpdate(modelData.host, modelData.port) }
                                            TextButton { text: "Actualizar"; enabled: !!(modelData.online && modelData.update && modelData.update.supported && modelData.update.available && ["available", "failed", "rolled_back"].indexOf(modelData.update.phase) >= 0); onClicked: { updatingDevice = modelData; updateDialog.open() } }
                                        }
                                        CheckBox {
                                            visible: !!(modelData.update && modelData.update.supported)
                                            text: "Actualizar automáticamente"
                                            font.pixelSize: 11
                                            checked: !!(modelData.update && modelData.update.auto_install)
                                            onClicked: backend.setAutoUpdate(modelData.host, modelData.port, checked)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Repeater {
                model: backend.syncConflicts
                delegate: Card {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.leftMargin: 22
                    Layout.rightMargin: 22
                    Layout.preferredHeight: 166
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        Text { text: modelData.name + " · " + modelData.reason; color: danger; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: "Agent: " + modelData.agent_summary; color: textMain; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: "Pantalla: " + modelData.device_summary; color: textMain; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        RowLayout {
                            TextButton { text: "Conservar perfil de Agent"; onClicked: backend.resolveMachineConflict(modelData.id, modelData.host, modelData.port, false) }
                            TextButton { text: "Usar perfil de la pantalla"; onClicked: backend.resolveMachineConflict(modelData.id, modelData.host, modelData.port, true) }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.bottomMargin: 22
                spacing: 16

                Card {
                    Layout.preferredWidth: 380
                    Layout.preferredHeight: 240

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 11

                        SectionTitle { text: "CONFIGURACIÓN" }
                        TextField {
                            id: nameField
                            Layout.fillWidth: true
                            implicitHeight: 44
                            text: backend.agentName
                            color: textMain
                            placeholderText: "Nombre del agente"
                            placeholderTextColor: textMuted
                            background: Rectangle {
                                radius: 10
                                color: raised
                                border.color: nameField.activeFocus ? primary : border
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "La conexión se configura automáticamente. No necesitas elegir puertos."
                            color: textMuted
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }
                        Switch {
                            text: "Iniciar con la computadora"
                            checked: backend.startsWithComputer
                            palette.windowText: textMain
                            onToggled: backend.setStartsWithComputer(checked)
                        }
                        Item { Layout.fillHeight: true }
                        RowLayout {
                            Layout.fillWidth: true
                            ZeuzButton {
                                text: "GUARDAR"
                                onClicked: backend.saveIdentity(nameField.text, backend.port)
                            }
                            ZeuzButton {
                                text: "REVOCAR ACCESOS"
                                buttonColor: dangerSoft
                                borderColor: "#F3C5CD"
                                labelColor: danger
                                onClicked: revokeDialog.open()
                            }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 260

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            SectionTitle {
                                Layout.fillWidth: true
                                text: "ACTIVIDAD RECIENTE"
                            }
                            TextButton {
                                text: "Limpiar"
                                onClicked: backend.clearActivity()
                            }
                        }

                        ListView {
                            id: activityList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            model: backend.activity
                            delegate: Rectangle {
                                required property var modelData
                                width: activityList.width
                                height: messageText.implicitHeight + 16
                                radius: 9
                                color: raised
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 9
                                    Text {
                                        text: modelData.time
                                        color: textMuted
                                        font.family: "Consolas"
                                        font.pixelSize: 11
                                    }
                                    Rectangle {
                                        Layout.preferredWidth: 7
                                        Layout.preferredHeight: 7
                                        radius: 4
                                        color: modelData.level === "error" ? danger
                                             : modelData.level === "warning" ? warning
                                             : success
                                    }
                                    Text {
                                        id: messageText
                                        Layout.fillWidth: true
                                        text: modelData.message
                                        color: textMain
                                        font.pixelSize: 12
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    property var updatingDevice: ({})
    Dialog {
        id: updateDialog
        title: "Actualizar " + (updatingDevice.name || "equipo")
        anchors.centerIn: parent
        modal: true
        width: Math.min(420, window.width - 40)
        standardButtons: Dialog.Ok | Dialog.Cancel
        Label { width: parent.width; wrapMode: Text.Wrap; text: "Se instalará la versión " + ((updatingDevice.update || {}).latest_version || "disponible") + ". El equipo esperará a que termine cualquier envío y se reconectará automáticamente. Se conservan programas, perfiles y configuración." }
        onAccepted: backend.installDeviceUpdate(updatingDevice.host, updatingDevice.port, updatingDevice.update.latest_revision)
    }

    Dialog {
        id: deviceNameDialog
        title: "Nombre del dispositivo"
        anchors.centerIn: parent
        modal: true
        width: 380
        standardButtons: Dialog.Save | Dialog.Cancel
        TextField { id: deviceNameField; width: parent.width; placeholderText: "Ejemplo: Torno norte"; maximumLength: 80 }
        onAccepted: backend.renameDevice(renamingDevice.host, renamingDevice.port, deviceNameField.text)
    }

    Dialog {
        id: machineDialog
        anchors.centerIn: parent
        width: Math.min(window.width - 48, 680)
        height: Math.min(window.height - 48, 650)
        modal: true
        title: editingMachineId.length > 0 ? "Editar máquina" : "Agregar máquina"
        standardButtons: Dialog.NoButton

        contentItem: ScrollView {
            clip: true
            ColumnLayout {
                width: machineDialog.availableWidth
                spacing: 12

                Text {
                    Layout.fillWidth: true
                    text: "Identifica la CNC, asígnale su Orange Pi y guarda los parámetros del control."
                    color: textMuted
                    wrapMode: Text.Wrap
                }
                Text {
                    visible: backend.machineError.length > 0
                    text: backend.machineError
                    color: danger
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                    font.pixelSize: 13
                }

                TextField {
                    id: machineNameField
                    Layout.fillWidth: true
                    placeholderText: "Nombre visible, por ejemplo Torno Mori 1"
                    color: textMain
                    placeholderTextColor: textMuted
                }
                RowLayout {
                    Layout.fillWidth: true
                    TextField {
                        id: machineHostField
                        Layout.fillWidth: true
                        placeholderText: "Orange Pi · zeuz-dnc-xxxx.local"
                        color: textMain
                        placeholderTextColor: textMuted
                    }
                    SpinBox { id: machinePortField; from: 1; to: 65535; value: 5000; editable: true }
                }
                SectionTitle { text: "COMUNICACIÓN SERIAL" }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 4
                    columnSpacing: 10
                    rowSpacing: 8
                    Text { text: "Baudrate"; color: textMuted }
                    SpinBox { id: baudField; from: 110; to: 256000; value: 9600; editable: true; Layout.fillWidth: true }
                    Text { text: "Bits de datos"; color: textMuted }
                    ComboBox { id: dataBitsBox; model: [5, 6, 7, 8]; currentIndex: 3; Layout.fillWidth: true }
                    Text { text: "Paridad"; color: textMuted }
                    ComboBox { id: parityBox; model: ["Ninguna", "Par", "Impar", "Mark", "Space"]; Layout.fillWidth: true }
                    Text { text: "Bits de stop"; color: textMuted }
                    ComboBox { id: stopBitsBox; model: [1, 2]; Layout.fillWidth: true }
                    Text { text: "Control de flujo"; color: textMuted }
                    ComboBox { id: flowBox; model: ["XON/XOFF", "RTS/CTS", "Ninguno"]; Layout.fillWidth: true }
                    Text { text: "Fin de línea"; color: textMuted }
                    ComboBox { id: terminatorBox; model: ["CR", "CRLF", "LF"]; currentIndex: 1; Layout.fillWidth: true }
                }
                RowLayout {
                    CheckBox { id: dtrCheck; text: "DTR"; palette.windowText: textMain }
                    CheckBox { id: rtsCheck; text: "RTS"; palette.windowText: textMain }
                    CheckBox { id: dripCheck; text: "Modo goteo (drip-feed)"; palette.windowText: textMain }
                }
                Text {
                    Layout.fillWidth: true
                    text: "Confirma estos valores contra el manual de la CNC antes del primer envío."
                    color: warning
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    ZeuzButton {
                        text: "CANCELAR"
                        buttonColor: raised
                        labelColor: textMain
                        borderColor: border
                        onClicked: machineDialog.close()
                    }
                    ZeuzButton { text: "GUARDAR MÁQUINA"; onClicked: saveMachine() }
                }
            }
        }
        background: Rectangle { radius: 18; color: surface; border.color: border }
    }

    Dialog {
        id: revokeDialog
        anchors.centerIn: parent
        width: 460
        modal: true
        title: "Revocar todos los accesos"
        standardButtons: Dialog.Cancel | Dialog.Ok
        onAccepted: backend.revokeAllDevices()
        contentItem: Text {
            text: "Todos los iPhone, dispositivos Zeuz y computadoras emparejados perderán acceso. Se generará un token y un código nuevos."
            color: textMain
            wrapMode: Text.Wrap
            padding: 16
        }
        background: Rectangle {
            radius: 16
            color: surface
            border.color: window.border
        }
    }

    footer: Rectangle {
        height: 30
        color: window.surface
        border.color: window.border
        border.width: 1
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            Text {
                text: backend.trayAvailable
                      ? "Cerrar la ventana mantiene el agente activo en la bandeja."
                      : "La bandeja del sistema no está disponible."
                color: textMuted
                font.pixelSize: 11
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "v" + backend.version
                color: textMuted
                font.pixelSize: 11
            }
        }
    }
}
