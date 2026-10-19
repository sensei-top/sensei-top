# Which projector wrote the derived rows. The watcher stores it in
# projection_state.projector_version after each rebuild and treats a stored
# value that differs (or is NULL) as dirty, so the first poll after an upgrade
# rebuilds. Bump it by hand in any commit that changes what project() derives
# from the same raw_events: a parsing fix, a new derived column, a corrected
# rule. Leave it alone for a change that derives the same rows. It is not the
# app's version.
PROJECTOR_VERSION = 3
