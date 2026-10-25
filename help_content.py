"""Offline English help text for Universal Linux Software Manager.

This module deliberately imports no Qt or network libraries; topics can be
validated by the release tests even on a headless build machine.
"""

# category, stable anchor, navigation title, HTML body. Only static, authored
# HTML is allowed in the document (never package names or network responses).
TOPICS = [
    (
        'Getting Started', 'welcome', 'Welcome',
        '''<p><b>Universal Linux Software Manager</b> helps you install and remove
        supported local Linux packages, check supported updates, inspect
        upstream software releases, and make local application-and-settings
        backups.</p>
        <p>This help is built into the application and works <b>offline</b>.
        Press <b>F1</b> anywhere in the application to open the chapter related
        to the tab you are using.</p>
        <h3>Quick start</h3>
        <ol>
          <li>Choose the tab that matches the package you have: Flatpak,
          AppImage, RPM, DEB, Arch, or Snap.</li>
          <li>Use <b>Install ... file</b> or drag a compatible package into the
          drop area. The application may ask for confirmation or authorization.</li>
          <li>Use <b>Refresh</b> to reload installed applications. Select a row
          before using <b>Uninstall selected</b>.</li>
          <li>Use <b>Updates</b> for source-aware update checks and <b>Discover</b>
          to browse software without making changes.</li>
          <li>Use <b>Backup / Restore</b> to save local installers and supported
          desktop settings in a <code>.bu</code> archive.</li>
        </ol>
        <p><b>Important:</b> This is not a replacement for every distribution's
        system package manager. Unsupported managers and risky system operations
        are intentionally unavailable.</p>'''
    ),
    (
        'Getting Started', 'navigation', 'Navigation and shortcuts',
        '''<h3>Navigate the application</h3>
        <p>The six package tabs list detected installed applications for their
        corresponding formats. Each provides installation, search, refresh and
        a guarded removal flow where available. Updates, Discover, Backup / Restore
        and Info are separate tabs.</p>
        <table cellspacing="0" cellpadding="6" border="1">
         <tr><th>Action</th><th>Shortcut or control</th></tr>
         <tr><td>Open contextual help</td><td><b>F1</b></td></tr>
         <tr><td>Search this help</td><td><b>Ctrl+F</b> while in Info</td></tr>
         <tr><td>Search installed applications</td><td>Type in the tab's search field</td></tr>
         <tr><td>Search Discover</td><td>Enter a term (at least two characters), press Enter or Search</td></tr>
         <tr><td>Navigate help topics</td><td>Choose the left-hand contents tree, or click a document link</td></tr>
         <tr><td>Return to a help topic</td><td>Back / Forward buttons in Info</td></tr>
        </table>
        <p>The Info tab is read-only. Reading a help topic never installs,
        removes, downloads or changes packages.</p>'''
    ),
    (
        'Package Formats', 'comparison', 'Choosing a package format',
        '''<p>Linux software can be distributed in several formats. A package
        format is not the same thing as a download source or application identity.
        Always confirm the publisher and package ID before installing.</p>
        <table cellspacing="0" cellpadding="6" border="1">
          <tr><th>Format</th><th>Typical use</th><th>Updates / isolation</th></tr>
          <tr><td><b>Flatpak</b></td><td>Cross-distribution desktop apps</td><td>Usually sandboxed; updates from its configured remote</td></tr>
          <tr><td><b>AppImage</b></td><td>Portable application file</td><td>Normally runs without installation; isolation is not automatic</td></tr>
          <tr><td><b>RPM</b></td><td>Fedora, openSUSE and related families</td><td>Native packages; dependencies and system policies apply</td></tr>
          <tr><td><b>DEB</b></td><td>Debian, Ubuntu and derivatives</td><td>Native packages; managed by APT/dpkg</td></tr>
          <tr><td><b>Arch</b></td><td>Arch, Manjaro and related distributions</td><td>Native pacman packages; often installed system-wide</td></tr>
          <tr><td><b>Snap</b></td><td>Systems with snapd</td><td>Managed by snapd; confinement depends on snap packaging</td></tr>
        </table>
        <h3>Which is better?</h3>
        <p><b>Flatpak</b> is often convenient for the same desktop app across
        distributions. <b>Native packages</b> fit closely with your distribution
        but can affect system dependencies. <b>AppImage</b> is convenient for
        portable files but must come from a trusted publisher. <b>Snap</b>
        needs snapd and a suitable installation source. No format is always
        best for every user or program.</p>
        <p><b>Do not mix sources casually:</b> installing a GitHub AppImage over
        a Flatpak with the same app name does not constitute a safe update.
        See <a href="#updates">Updates</a> and
        <a href="#security">Security and package sources</a>.</p>'''
    ),
    (
        'Package Formats', 'flatpak', 'Flatpak',
        '''<p>Flatpak installs desktop software and runtimes independently of
        the host distribution. A <b>remote</b> (for example Flathub) supplies
        apps and updates; a local <code>.flatpak</code> bundle contains an app,
        while a <code>.flatpakref</code> points to a remote installation.</p>
        <h3>In this application</h3>
        <p>Choose the <b>Flatpak</b> tab, select a supported file, or drag it
        into the drop area. The app can show user and system installations.
        Their scopes are not interchangeable. For removal, the app checks the
        specific Flatpak reference so similarly named branches are not removed
        accidentally.</p>
        <h3>Advantages and considerations</h3>
        <p><b>Pros:</b> broad distribution support, desktop integration, and
        sandbox permissions for many apps. <b>Consider:</b> initial runtimes
        may require internet access and disk space; sandbox access varies;
        app data can survive uninstallation if you choose to keep it.</p>
        <p>Do not interpret <b>USER</b> as untrusted and <b>SYSTEM</b> as
        automatically safe. Those labels describe installation scope, not
        publisher reputation.</p>'''
    ),
    (
        'Package Formats', 'appimage', 'AppImage',
        '''<p>An <code>.AppImage</code> is generally a portable executable file
        containing an application and many of its libraries. It does not
        automatically provide a security sandbox or guaranteed automatic
        updates.</p>
        <h3>In this application</h3>
        <p>The <b>AppImage</b> tab can manage AppImages placed in the user's
        <code>~/Applications</code> directory and their desktop launchers.
        Removal is limited to AppImages the manager can safely recognize as
        managed. Other user data is not automatically deleted.</p>
        <p>Update support depends on a known trusted source or a linked GitHub
        release. The app should replace a managed AppImage rather than keep
        an old duplicate. A file without a reliable source might be listed
        as <b>Check unavailable</b>.</p>
        <p><b>Security:</b> an AppImage is executable code. Only run releases
        from publishers you trust; changing an executable bit does not verify
        authenticity.</p>'''
    ),
    (
        'Package Formats', 'rpm', 'RPM: DNF, Zypper and rpm-ostree',
        '''<p>RPM is a native package format used by several distribution
        families, but the host's package manager determines how RPM changes
        are performed. The application selects a compatible manager; it
        does <b>not</b> run Fedora commands on openSUSE.</p>
        <h3>Distribution-specific behavior</h3>
        <p><b>Fedora / DNF:</b> uses dependency-aware operations and safe
        removal previews. <b>openSUSE / Zypper:</b> checks the intended RPM
        transaction with a dry run and protected-package rules. <b>Bazzite
        / Fedora Atomic (rpm-ostree):</b> manages requested package layers;
        a reboot can be required for changes to take effect.</p>
        <p>The RPM list aims to display user-facing installed applications,
        not every system package. It filters known desktop components and
        protected packages. Some command-line tools may therefore be hidden.
        The protection is conservative, not an absolute guarantee.</p>
        <p><b>Important:</b> a dependency test and a transaction preview
        can fail or change if the system's package state changes. Never remove
        core RPMs or Plasma components to clear space. Immutable or
        transactional openSUSE variants may not support ordinary Zypper writes.</p>'''
    ),
    (
        'Package Formats', 'deb', 'DEB: Debian and Ubuntu',
        '''<p><code>.deb</code> is the native package format on Debian, Ubuntu,
        Xubuntu, Linux Mint and many derivatives. APT resolves dependencies;
        dpkg handles individual installed package records.</p>
        <p>Use the <b>DEB</b> tab for a compatible local installer. The app
        safeguards removals using package protections and a dry-run check;
        removal is offered only when the preview does not require removing
        unrelated packages.</p>
        <p><b>Pros:</b> tight integration with your distribution and its
        updates. <b>Consider:</b> third-party files can have system-wide
        effects; an arbitrary downloaded DEB does not automatically gain a
        trusted update repository.</p>'''
    ),
    (
        'Package Formats', 'arch', 'Arch and pacman',
        '''<p>Arch Linux and derivatives use pacman and native
        <code>.pkg.tar.*</code> packages. Installing a local package can still
        depend on the rest of the system and repository state.</p>
        <p>The <b>Arch</b> tab is enabled only when the supported host manager
        is detected. The application checks explicit package ownership,
        protected system packages, and the removal plan before continuing.</p>
        <p><b>Consider:</b> on rolling-release distributions, partial updates
        can break dependency compatibility. Prefer normal full system
        maintenance through your distribution's tools; do not remove kernel,
        desktop or pacman components to resolve a package conflict.</p>'''
    ),
    (
        'Package Formats', 'snap', 'Snap',
        '''<p>Snap packages are managed by <b>snapd</b>. A local
        <code>.snap</code> may be accompanied by a signed
        <code>.assert</code> assertion. Local Snap installation is unavailable
        when the host does not provide snapd.</p>
        <p>The <b>Snap</b> tab prefers a signed package and assertion. Without
        a matching assertion, the app warns and asks for explicit confirmation
        before invoking Snap's <code>--dangerous</code> mode. The default
        answer is <b>No</b>.</p>
        <p><b>Warning:</b> <code>--dangerous</code> bypasses the normal
        assertion/signature verification. It does not scan the application
        for malware. Use it only if you understand and trust the origin.
        Confinement depends on the Snap's declared permissions.</p>'''
    ),
    (
        'Using the Manager', 'installing', 'Install, uninstall and refresh',
        '''<h3>Install a local package</h3>
        <ol><li>Select the matching format tab.</li>
        <li>Choose <b>Install ... file</b> or drop one compatible file into
        the drop area.</li><li>Read the proposed action, source, permissions
        and dependency prompts before approving.</li><li>Wait for the result
        and use <b>Refresh</b> if the installed list has changed.</li></ol>
        <h3>Remove an application</h3>
        <p>Choose exactly one listed app and select <b>Uninstall selected</b>.
        Confirm the target and any proposed transaction. Protected core
        packages, unsupported managers and ambiguous ownership should block
        removal. The red button is deliberately destructive.</p>
        <h3>Why might a tab be empty or disabled?</h3>
        <p>The package manager may not exist on the host, the distro family
        may not support that format, or there may be no safely recognized
        user-installed applications. <b>Refresh</b> reloads inventory; it
        cannot enable an unsupported package manager.</p>
        <p>A package operation may require administrator authorization.
        The window prevents closing while critical operations are running
        so that a host-side operation is not abandoned without a result.</p>'''
    ),
    (
        'Using the Manager', 'updates', 'Updates and source preservation',
        '''<p>The <b>Updates</b> tab checks installed software from supported
        sources and shows available versions and statuses. Additional native
        families may appear for read-only checking without an install tab.</p>
        <h3>Know the original installation source</h3>
        <p>An update must follow the app's existing managed source. A Flathub
        Flatpak is not replaced automatically with a GitHub AppImage, even if
        both have the same name. The program can require you to remove an old
        installation explicitly before changing sources.</p>
        <p><b>Update all</b> attempts only updates with a supported, safe route.
        Searching filters the visible list; it is not a promise that every
        package format can be updated. Statuses such as <b>No update found</b>,
        <b>Unknown source</b>, <b>Check unavailable</b>, <b>Use system updater</b>,
        and <b>Reboot required</b> have different meanings.</p>
        <p>If the updater asks you to switch to the relevant AppImage or other
        installation tab, follow its explicit confirmation and removal flow;
        do not install two unrelated copies just to match a version number.</p>'''
    ),
    (
        'Using the Manager', 'discover', 'Discover: browse without installing',
        '''<p><b>Discover is strictly read-only.</b> It searches software
        catalogs and connected upstream sources such as local package indexes,
        Flathub and GitHub, subject to network availability.</p>
        <p>Search for at least two characters. Select a result's <b>name</b>
        to inspect supported GitHub release history or Flatpak build/commit
        history. Open a trusted upstream project page in your browser or copy
        a Flatpak commit identifier when available.</p>
        <p><b>Discover never downloads, installs, uninstalls, upgrades,
        downgrades or switches a package source.</b> Viewing a release version
        is not an installation action. Other package sources might not
        expose usable public version history.</p>
        <p>Results with similar names may come from different publishers.
        Compare package IDs, repositories and release pages instead of
        assuming they are the same application.</p>'''
    ),
    (
        'Using the Manager', 'backup', 'Backup and Restore (.bu)',
        '''<p>The <b>Backup / Restore</b> tab creates a local
        <code>.bu</code> archive containing selected local installer files and
        supported user desktop settings. It is <b>not</b> a full disk image,
        a complete system snapshot or an online cloud backup.</p>
        <h3>Create a backup</h3>
        <ol><li>Add the local package installer files you want to keep;
        drag and drop is supported.</li>
        <li>Select available desktop-setting categories such as display,
        audio, panels, appearance, keyboard, power and region.</li>
        <li>Choose <b>Create Backup</b>, review the destination and keep
        the <code>.bu</code> somewhere safe.</li></ol>
        <p>The app tries to exclude default distribution applications from
        the reinstall list. Applications installed only from online stores
        do not automatically become offline installer files in a backup.
        Check that you have the original installers.</p>
        <h3>Restore a backup</h3>
        <ol><li>Choose <b>Restore Backup</b> and open your existing
        <code>.bu</code>.</li><li>Review its contents and preflight warnings.</li>
        <li>When the preview asks for confirmation, click <b>Restore Backup</b>
        again to start the selected restore.</li><li>Package reinstall actions
        require individual review, can prompt for privileges and can be
        unavailable on another distro or CPU architecture.</li></ol>
        <p><b>Restart manually after restoring desktop settings.</b> Existing
        settings may be saved in restore-history for recovery. Different
        monitors, sound devices, desktops and versions can require manual
        adjustments. Never assume a successful archive check guarantees an
        identical desktop on different hardware.</p>'''
    ),
    (
        'Using the Manager', 'desktop', 'Desktop settings: KDE, GNOME and Xfce',
        '''<p>Desktop settings are user-specific and may be incompatible
        between different desktop environments or versions. The restore
        function applies only supported settings. Some categories can be
        empty when the current desktop has no matching custom configuration.</p>
        <h3>KDE Plasma</h3>
        <p>For supported systemd-managed KDE sessions, the app safely stages
        Plasma configuration files for a <b>one-time restore at the next
        login</b>. Display and panel settings are applied before KWin and
        Plasma load them. Live audio is handled separately after login.
        <b>Reboot required</b> means settings are staged, not yet verified.
        A customized or older KDE session without a suitable early-start
        service may reject deferred restore rather than claim success.</p>
        <h3>GNOME and Xfce</h3>
        <p>These desktops keep their existing supported restore procedures.
        Some settings only take effect after logging out or rebooting.
        Restoring an Xfce layout on GNOME, or KDE settings on Xfce, is not
        equivalent to migrating a desktop environment.</p>
        <h3>Screen and audio precautions</h3>
        <p>A saved resolution may not be supported by the current monitor,
        graphics session or VM display adapter. An audio sink saved on one
        computer can have a different device name on another. The app
        reports partial restoration instead of silently assuming that
        every stored device exists.</p>'''
    ),
    (
        'Using the Manager', 'security', 'Security, permissions and sources',
        '''<h3>USER versus SYSTEM</h3>
        <p><b>USER</b> means the installation applies to one account;
        <b>SYSTEM</b> means a system-wide installation. Neither label proves
        an app is safe. System-level package changes generally require
        administrator authorization and may affect other users.</p>
        <h3>Why do password prompts appear?</h3>
        <p>Linux desktop software centers and their PolicyKit helpers may
        request authentication for system-wide Flatpak installation, runtime
        installation, or package-manager operations. When a local
        <code>.flatpak</code> is opened by double-clicking, its software
        center controls that process. Some environments ask more than once
        for separate privileged steps. The manager itself cannot suppress
        authorization prompts from the installer that launches it.</p>
        <p>The app does not need you to type your password into its Info tab.
        Treat unexpected password windows carefully and check the action
        and requesting program. A user-scoped Flatpak installation often
        avoids system-wide administration, but it does not guarantee zero
        prompts in every desktop environment.</p>
        <h3>Where software comes from matters</h3>
        <p>Verify publishers, download URLs, signatures and release names.
        A GitHub repository, Flathub listing, local RPM and AppImage may have
        different maintainers. No single file extension certifies trust.
        A dry-run cannot guarantee that a future transaction is risk-free.</p>'''
    ),
    (
        'Help and Support', 'troubleshoot', 'Troubleshooting',
        '''<h3>The application will not install</h3>
        <p>Confirm Flatpak is installed on the Linux host. A downloaded
        <code>.flatpak</code> bundle can require a separate KDE Platform
        runtime download. A file manager's double-click action depends on
        a working software center. A local bundle differs from a
        <code>.flatpakref</code> reference.</p>
        <h3>No apps or missing native manager</h3>
        <p>Click <b>Refresh</b>. Check that the host actually supports the
        tab's package manager. System packages may be hidden on purpose.
        An empty list is not proof that your system has no installed packages.</p>
        <h3>Install/remove failed</h3>
        <p>Read the full transaction or dependency warning. Native backends
        may be blocked by a missing manager, repository errors, permissions,
        ownership checks or protected packages. Do not circumvent the
        safety check by forcing a system-package removal.</p>
        <h3>Discover or Updates appears empty</h3>
        <p>Discover needs a valid search term and may require network access.
        Updates need known sources and a supported checker; many packages
        legitimately report <b>Check unavailable</b>.</p>
        <h3>Restore completed but settings look unchanged</h3>
        <p>Check which desktop categories were actually saved. On KDE,
        <b>Reboot required</b> indicates a pending one-time restore, not
        success. Reboot yourself into the same KDE session type and check
        the resulting desktop. Audio and display hardware differences can
        produce warnings or partial results.</p>
        <h3>A backup archive is incomplete or too large</h3>
        <p>A <code>.bu</code> archive can only contain supplied installer
        files and captured settings. It does not automatically download
        every package you installed. Large installers require free storage
        on both backup and restore destinations. Keep an independent copy
        of important data.</p>'''
    ),
    (
        'Help and Support', 'faq', 'Frequently asked questions',
        '''<h3>Can I use this on every Linux distribution?</h3>
        <p>The interface can run on many distributions when its Flatpak
        runtime is available, but native package operations require the
        specific manager and host checks. Some additional package families
        only support read-only update discovery.</p>
        <h3>Does Discover install programs?</h3>
        <p>No. Discover only searches, shows available upstream history
        and opens pages. Use the appropriate installation tab for supported
        local installers.</p>
        <h3>Does the backup include my whole operating system?</h3>
        <p>No. The <code>.bu</code> archive stores selected installers and
        supported user desktop preferences, not the OS, every package,
        every home file, or a complete disk image.</p>
        <h3>Can I restore an archive on another Linux distribution?</h3>
        <p>You may inspect it, but incompatible package formats, different
        CPU architectures, desktop environments and hardware can prevent
        parts from restoring. Only explicitly confirmed supported actions
        are attempted.</p>
        <h3>Will my packages update automatically?</h3>
        <p>The Updates tab performs checks and offers supported actions;
        it does not promise background upgrades of every app or switch
        software sources on its own.</p>
        <h3>Why is a package missing from the list?</h3>
        <p>The native system inventory intentionally hides core packages,
        and some packages lack recognizable desktop launchers or ownership
        information. This is a safety feature, not an exhaustive inventory.</p>
        <h3>Why is a reboot required after restoring KDE settings?</h3>
        <p>Plasma may rewrite active configuration files as it exits. The
        app stages supported KDE settings so they can be applied once
        before Plasma and KWin load them at the next login.</p>'''
    ),
    (
        'Help and Support', 'about', 'About, feedback and limits',
        '''<p><b>Universal Linux Software Manager</b> v1.0.0 is an evolving,
        multi-distribution desktop management application.</p>
        <p>The project provides conservative safety checks and confirmations
        but cannot guarantee that any package transaction, untrusted download,
        or cross-device settings restore will be risk-free. Prefer backups
        and your distribution's documented recovery tools for critical systems.</p>
        <h3>Share feedback</h3>
        <p>Use the <b>Send Feedback</b> and <b>Report a Bug</b> buttons below
        the main tabs. They open the project's discussion page in your
        regular browser. Describe your Linux distribution, desktop environment,
        package format, requested action, and the exact error message.
        Do not publish passwords or private data in issue reports.</p>
        <p>Project repository: <code>github.com/LionheartTim/Universal-Linux-Software-Manager</code></p>
        <p>Help documentation is available offline. Update listings,
        GitHub release history, and some discovery results require a
        network connection.</p>'''
    ),
]

TOPIC_IDS = [topic[1] for topic in TOPICS]
TOPIC_BY_ID = {topic[1]: topic for topic in TOPICS}
