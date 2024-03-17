import {ActionType, TaskArguments} from 'hardhat/types';
import { format } from 'util';

/**
 * A wrapper for commands that should "return" (log to stdout) only json
 * Patches stdout so that console.log can still be used, and assumes the action returns a JSON-serializable value.
 * This is used internally in tests with HardhatService.run_json_command.
 * @param action
 */
export const jsonAction = (action: ActionType<TaskArguments>): ActionType<TaskArguments> => {
    return async (...args) => {
        // Patch console, but only whatever goes to stdout
        const origWrite = process.stdout.write;
        // Apparently patching process.stdout.write above is not enough, so we also patch console.log
        // don't bother patching info/debug/etc for now
        const origLog = console.log;
        process.stdout.write = process.stderr.write;
        console.log = (...args) => {
            const formatted = format(...args);
            process.stderr.write('[JSONTASK] ' + formatted + '\n');
        }
        let ret: any;
        try {
            ret = await action(...args);
        } finally {
            process.stdout.write = origWrite;
            console.log = origLog;
        }
        console.log(JSON.stringify(ret, undefined, 4));
        return ret;
    };
}
