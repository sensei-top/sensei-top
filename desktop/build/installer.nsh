; Sensei Top's additions to electron-builder's assisted NSIS installer.
; Plan 6, D25: the installer only records the autostart choice in
; first-run.json beside the executable; the shell applies it on first launch.
; The JSON it writes is ASCII, so FileWrite's output is valid UTF-8 without a
; BOM. The script itself holds accented text (the LangStrings below), which
; makensis reads as UTF-8 because electron-builder passes -INPUTCHARSET UTF8.

; Change them here only. The second donation link is the site's Donate
; section, not a platform: a shipped installer can't change its links, and
; 1.0.0's pointed at a GitHub Sponsors page GitHub had not approved yet.
!define SENSEI_TOP_SOURCE_URL "https://github.com/sensei-top/sensei-top"
!define SENSEI_TOP_DONATE_URL "https://senseitop.com/#donate"
!define SENSEI_TOP_APOIASE_URL "https://apoia.se/senseitop"
; MUI's own link colour (MUI_FINISHPAGE_LINK_COLOR's default).
!define SENSEI_TOP_LINK_COLOR "000080"
; The LCID NSIS gives Brazilian Portuguese (LANG_PORTUGUESEBR). Spelt out
; because the finish page's functions, where the macro below is inserted,
; are compiled before electron-builder loads the languages, so the define
; does not exist there yet; a $(LangString) is late-bound, a ${define} is not.
!define SENSEI_TOP_LCID_PT_BR 1046

; The installer's language, for the shell's welcome step (plan 18, D4).
!macro SenseiTopWriteFirstRun AUTOSTART
  ${if} $LANGUAGE == ${SENSEI_TOP_LCID_PT_BR}
    StrCpy $1 "pt-BR"
  ${else}
    StrCpy $1 "en"
  ${endif}
  FileOpen $0 "$INSTDIR\first-run.json" w
  FileWrite $0 '{"autostart": ${AUTOSTART}, "language": "$1"}'
  FileClose $0
!macroend

!macro customHeader
  LangString SenseiTopWelcomeTitle ${LANG_ENGLISH} "Welcome to Sensei Top"
  LangString SenseiTopWelcomeTitle ${LANG_PORTUGUESEBR} "Bem-vindo ao Sensei Top"

  LangString SenseiTopWelcomeText ${LANG_ENGLISH} "Sensei Top turns the logs that Magic: The Gathering Arena and Magic Online already write on this computer into match history, matchup records and post-game reviews.$\r$\n$\r$\nIt is free software under the GNU Affero General Public License, version 3: you may use, study, change and share it. No account, no ads, nothing to buy.$\r$\n$\r$\nClick Next to continue."
  LangString SenseiTopWelcomeText ${LANG_PORTUGUESEBR} "O Sensei Top transforma os logs que o Magic: The Gathering Arena e o Magic Online já escrevem neste computador em histórico de partidas e de matchups e em relatórios pós-jogo.$\r$\n$\r$\nÉ software livre sob a GNU Affero General Public License, versão 3: você pode usar, estudar, alterar e compartilhar. Sem conta, sem anúncios, nada a comprar.$\r$\n$\r$\nClique em Avançar para continuar."

  LangString SenseiTopSourceLink ${LANG_ENGLISH} "Source code: ${SENSEI_TOP_SOURCE_URL}"
  LangString SenseiTopSourceLink ${LANG_PORTUGUESEBR} "Código-fonte: ${SENSEI_TOP_SOURCE_URL}"

  LangString SenseiTopAutostart ${LANG_ENGLISH} "Start Sensei Top when Windows starts"
  LangString SenseiTopAutostart ${LANG_PORTUGUESEBR} "Abrir o Sensei Top quando o Windows iniciar"

  LangString SenseiTopDonationNote ${LANG_ENGLISH} "Sensei Top is free: no ads, nothing to buy. Donations alone keep it maintained. If it helps your games, support it on:"
  LangString SenseiTopDonationNote ${LANG_PORTUGUESEBR} "O Sensei Top é gratuito: sem anúncios, nada a comprar. Só as doações o mantêm. Se ele ajuda nas suas partidas, apoie em:"

  LangString SenseiTopDonateLink ${LANG_ENGLISH} "Other ways to donate"
  LangString SenseiTopDonateLink ${LANG_PORTUGUESEBR} "Outras formas de doar"

  LangString SenseiTopApoiaseLink ${LANG_ENGLISH} "Apoia.se (Brazil)"
  LangString SenseiTopApoiaseLink ${LANG_PORTUGUESEBR} "Apoia.se (Brasil)"

  LangString SenseiTopUninstalled ${LANG_ENGLISH} "Sensei Top was removed. Your match history was kept in:$\r$\n$LOCALAPPDATA\Sensei Top$\r$\n$\r$\nand your settings in:$\r$\n$APPDATA\sensei-top$\r$\n$\r$\nDelete those folders to remove them too. An API key you saved stays in Windows Credential Manager, under sensei-top."
  LangString SenseiTopUninstalled ${LANG_PORTUGUESEBR} "O Sensei Top foi removido. Seu histórico de partidas foi mantido em:$\r$\n$LOCALAPPDATA\Sensei Top$\r$\n$\r$\ne suas configurações em:$\r$\n$APPDATA\sensei-top$\r$\n$\r$\nApague essas pastas para removê-los também. Uma chave de API que você salvou continua no Gerenciador de Credenciais do Windows, em sensei-top."
!macroend


; The first page says what the program is and that it is free software, as
; free-software installers do (Audacity, OBS). MUI's welcome page has no link
; slot, so the source link is added in the page's show hook, at the spot the
; finish page uses for its own link.
!macro customWelcomePage
  !define MUI_WELCOMEPAGE_TITLE "$(SenseiTopWelcomeTitle)"
  !define MUI_WELCOMEPAGE_TEXT "$(SenseiTopWelcomeText)"
  !define MUI_PAGE_CUSTOMFUNCTION_SHOW SenseiTopWelcomeShow
  !insertmacro MUI_PAGE_WELCOME

  Function SenseiTopWelcomeShow
    ${NSD_CreateLink} 120u 175u 195u 10u "$(SenseiTopSourceLink)"
    Pop $0
    SetCtlColors $0 "${SENSEI_TOP_LINK_COLOR}" "${MUI_BGCOLOR}"
    ${NSD_OnClick} $0 SenseiTopOpenSource
  FunctionEnd

  Function SenseiTopOpenSource
    Pop $0
    ExecShell open "${SENSEI_TOP_SOURCE_URL}"
  FunctionEnd
!macroend

; Per user only (D22). multiUserUi.nsh inserts this macro before its
; install-mode page; the force flag skips that page and installs under
; %LOCALAPPDATA%\Programs, also when the installer was run elevated. Two
; paths still go per-machine, both on purpose: an explicit /allusers on the
; command line, and a silent run over an existing per-machine install.
!macro customInstallMode
  StrCpy $isForceCurrentInstall "1"
!macroend

; The finish page keeps the template's "Run" box (its block is copied from
; assistedInstaller.nsh) and adds a second box, MUI's readme slot, for the
; autostart choice: unticked. The choice is recorded in the page's leave hook,
; not in the readme box's function: MUI runs the Run box's function first, and
; the app it launches reads first-run.json at once. Below the boxes, the show
; hook adds the donation note, a link to the site's Donate section and one
; to Apoia.se (ROADMAP.md, "Donations"); MUI's single link slot would sit
; under them at 175u, so it is left unused.
!macro customFinishPage
  !ifndef HIDE_RUN_AFTER_FINISH
    Function StartApp
      ${if} ${isUpdated}
        StrCpy $1 "--updated"
      ${else}
        StrCpy $1 ""
      ${endif}
      ${StdUtils.ExecShellAsUser} $0 "$launchLink" "open" "$1"
    FunctionEnd

    !define MUI_FINISHPAGE_RUN
    !define MUI_FINISHPAGE_RUN_FUNCTION "StartApp"
  !endif

  !define MUI_FINISHPAGE_SHOWREADME ""
  !define MUI_FINISHPAGE_SHOWREADME_TEXT "$(SenseiTopAutostart)"
  !define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
  ; MUI would run ExecShell on an empty name without a function.
  !define MUI_FINISHPAGE_SHOWREADME_FUNCTION "SenseiTopAutostartChosen"
  !define MUI_PAGE_CUSTOMFUNCTION_SHOW SenseiTopFinishShow
  !define MUI_PAGE_CUSTOMFUNCTION_LEAVE SenseiTopRecordAutostart
  !insertmacro MUI_PAGE_FINISH

  ; The boxes end at 120u (MUI: text 45u-85u, Run at 90u, autostart at 110u).
  Function SenseiTopFinishShow
    ${NSD_CreateLabel} 120u 132u 195u 26u "$(SenseiTopDonationNote)"
    Pop $0
    SetCtlColors $0 "${MUI_TEXTCOLOR}" "${MUI_BGCOLOR}"

    ${NSD_CreateLink} 120u 162u 150u 10u "$(SenseiTopDonateLink)"
    Pop $0
    SetCtlColors $0 "${SENSEI_TOP_LINK_COLOR}" "${MUI_BGCOLOR}"
    ${NSD_OnClick} $0 SenseiTopOpenDonate

    ${NSD_CreateLink} 120u 175u 100u 10u "$(SenseiTopApoiaseLink)"
    Pop $0
    SetCtlColors $0 "${SENSEI_TOP_LINK_COLOR}" "${MUI_BGCOLOR}"
    ${NSD_OnClick} $0 SenseiTopOpenApoiase
  FunctionEnd

  Function SenseiTopOpenDonate
    Pop $0
    ExecShell open "${SENSEI_TOP_DONATE_URL}"
  FunctionEnd

  Function SenseiTopOpenApoiase
    Pop $0
    ExecShell open "${SENSEI_TOP_APOIASE_URL}"
  FunctionEnd

  ; The leave hook already recorded the choice.
  Function SenseiTopAutostartChosen
  FunctionEnd

  ; Defined after MUI_PAGE_FINISH, which declares $mui.FinishPage.ShowReadme.
  ; Unticked writes nothing: customInstall already wrote "false".
  Function SenseiTopRecordAutostart
    ${NSD_GetState} $mui.FinishPage.ShowReadme $0
    ${if} $0 == ${BST_CHECKED}
      !insertmacro SenseiTopWriteFirstRun true
    ${endIf}
  FunctionEnd
!macroend

; Runs inside the install section, before the finish page: the file always
; exists, "false" unless the box is ticked. A silent update (electron-updater)
; never shows the page, so it must not overwrite what is already recorded.
!macro customInstall
  ${ifNot} ${isUpdated}
    !insertmacro SenseiTopWriteFirstRun false
  ${endIf}
!macroend

; electron-updater runs the old uninstaller on every update, so the login
; entry goes only on a real uninstall.
!macro customUnInstall
  ${ifNot} ${isUpdated}
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Sensei Top"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" "Sensei Top"
  ${endIf}
!macroend

; The uninstaller's last page: the data was kept, and where it is.
!macro customUninstallPage
  !define MUI_FINISHPAGE_TEXT "$(SenseiTopUninstalled)"
!macroend
