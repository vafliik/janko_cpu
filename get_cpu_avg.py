#! /usr/bin/python3
############################################################################
# Copyright 2013 George Hansper                                            #
# This program has been made available to the Open Source community for    #
# redistribution and further development under the terms of the            #
# GNU General Public License v2: http://www.gnu.org/licenses/gpl-2.0.html  #
############################################################################
# This program is supplied 'as-is', in the hope that it will be useful,    #
# but the author does not make any warranties or guarantees as             #
# to its correct operation.                                                #
#                                                                          #
# Or in other words:                                                       #
#       Test it yourself, and make sure it works for YOU.                  #
############################################################################
# Author: George Hansper                     e-mail:  george@hansper.id.au #
# This plugin was originally based on check_cpu.py written by              #
# Kirk Hammond <kirkdhammond@gmail.com>                                    #
############################################################################
import json
import os

Version = "1.0"

# import modules
import sys, getopt, time
from datetime import datetime, timedelta


# nagios return codes
UNKNOWN = 3
OK = 0
WARNING = 1
CRITICAL = 2

# Usage message
usage = """usage: ./check_cpu.py [-w num|--warn=num] [-c|--crit=num] [-t|--time=num] [-f|--file=str]
	-w, --warn     ... generate warning  if total cpu exceeds num (default: 95)
	-c, --crit     ... generate critical if total cpu exceeds num (default: 98)
	-t, --time     ... analyze results from previous (num) minutes (default: 10)
	-f, --file     ... previous measurements filename (default: '/tmp/SalsitaCustomNCPANagiosChecks/results.json')
	-v  --version  ... print(version)

Notes:
	Warning/critical alerts are generated when the threshold is exceeded
	eg -w 95 means alert on 96% and above
	All values are in percent, but no % symbol is required
"""

cpu_percent = {}
io_wait_percent = {}
steal_percent = {}
cpu_id_list = []
ctxt_per_second = 0
processes_per_second = 0
cpu_stats_t1 = {}
warn = 95
crit = 98
proc_stat_file = '/proc/stat'
sample_period = 1
perfdata_abs = 1
time_window_minutes = 10

# File containing results from previous measurements
file_path = '/tmp/SalsitaCustomNCPANagiosChecks/results.json'

# Generate actual timestamp
now = datetime.now()
timestamp = datetime.timestamp(now)


def read_historical_results():
    # x minutes ago
    ts_past = datetime.timestamp(now - timedelta(minutes=time_window_minutes))
    # Read the file
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            results = json.load(f)

        # Cleanup - remove older than 10 minutes
        results = {key: val for key, val in results.items() if float(key) >= ts_past}

    else:
        results = {}

    return results


def write_results_to_file(results):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
    except OSError as e:
        print("Can't create tmp dir\n" + str(e))
        sys.exit(CRITICAL)
    with open(file_path, 'w') as f:
        json.dump(results, f)


def get_procstat_now():
    global cpu_id_list, proc_stat_file
    cpu_id_list = []
    cpu_stats = dict()
    procstat = open(proc_stat_file, 'r')
    procstat_text = procstat.read()
    procstat.close()
    for line in procstat_text.split("\n"):
        if line.startswith('cpu '):
            [cpu_id, junk, cpu_ticks] = line.split(' ', 2)
        elif line.startswith('cpu'):
            [cpu_id, cpu_ticks] = line.split(' ', 1)
        elif line.startswith('ctxt '):
            cpu_stats['ctxt'] = line.split()[1]
            continue
        elif line.startswith('processes '):
            cpu_stats['processes'] = line.split()[1]
            continue
        else:
            continue
        # Fields are:
        # cpu user nice system idle io_wait hw_intr sw_intr steal guest guest_nice
        cpu_ticks_array = cpu_ticks.split()
        while len(cpu_ticks_array) < 10:
            cpu_ticks_array.append('0')
        [user, nice, system, idle, io_wait, hw_intr, sw_intr, steal, guest, guest_nice] = cpu_ticks_array
        cpu_usage = int(user) + int(nice) + int(system) + int(io_wait) + int(hw_intr) + int(sw_intr) + int(steal) + int(
            guest) + int(guest_nice)
        cpu_total_ticks = cpu_usage + int(idle)
        cpu_stats[cpu_id] = cpu_usage
        cpu_stats[cpu_id + 'all'] = cpu_total_ticks
        cpu_stats[cpu_id + 'io_wait'] = int(io_wait)
        cpu_stats[cpu_id + 'steal'] = int(steal)
        cpu_id_list.append(cpu_id)
    return cpu_stats


# Calculate cpu use for all cpus
def get_cpu_stats():
    global cpu_id_list, cpu_percent, io_wait_percent, sample_period, steal_percent, cpu_stats_t1, ctxt_per_second, processes_per_second
    cpu_stats_t0 = dict()
    cpu_stats_t1 = dict()
    cpu_stats_t0 = get_procstat_now()
    time.sleep(sample_period)
    cpu_stats_t1 = get_procstat_now()
    for cpu_id in cpu_id_list:
        if (cpu_stats_t1[cpu_id + 'all'] - cpu_stats_t0[cpu_id + 'all']) > 0:
            # The normal case
            io_wait_percent[cpu_id] = (cpu_stats_t1[cpu_id + 'io_wait'] - cpu_stats_t0[cpu_id + 'io_wait']) * 100 / (
                    cpu_stats_t1[cpu_id + 'all'] - cpu_stats_t0[cpu_id + 'all'])
            steal_percent[cpu_id] = (cpu_stats_t1[cpu_id + 'steal'] - cpu_stats_t0[cpu_id + 'steal']) * 100 / (
                    cpu_stats_t1[cpu_id + 'all'] - cpu_stats_t0[cpu_id + 'all'])
            cpu_percent[cpu_id] = (cpu_stats_t1[cpu_id] - cpu_stats_t0[cpu_id]) * 100 / (
                    cpu_stats_t1[cpu_id + 'all'] - cpu_stats_t0[cpu_id + 'all'])
        else:
            # The case of a VM that has had no cpu cycles devoted to this CPU at all
            io_wait_percent[cpu_id] = 0
            steal_percent[cpu_id] = 0
            cpu_percent[cpu_id] = 0
    ctxt_per_second = (float(cpu_stats_t1['ctxt']) - float(cpu_stats_t0['ctxt'])) / sample_period
    processes_per_second = (float(cpu_stats_t1['processes']) - float(cpu_stats_t0['processes'])) / sample_period
    return


# Build the status message (service output message) and set the exit code based on the average value from data
def check_status(avg):
    message = 'Average CPU Load in last {} minutes: {}'.format(time_window_minutes, avg)

    if avg > crit:
        message = 'CRITICAL - ' + message
        status_code = CRITICAL
    elif avg > warn:
        message = 'WARNING - ' + message
        status_code = WARNING
    else:
        message = 'OK - ' + message
        status_code = OK

    return status_code, message


# define command line options and validate data.  Show usage or provide info on required options
def command_line_validate(argv):
    global warn, crit, time_window_minutes, file_path

    try:
        opts, args = getopt.getopt(argv, 'w:c:t:f:V',
                                   ['warn=', 'crit=', 'time=', 'file=', 'version'])
    except getopt.GetoptError:
        print(usage)
        sys.exit(CRITICAL)
    try:
        for opt, arg in opts:
            arg = arg.rstrip('%')
            if opt in ('-w', '--warn'):
                try:
                    warn = int(arg)
                except:
                    print('***warn value must be an integer***')
                    sys.exit(CRITICAL)

            elif opt in ('-c', '--crit'):
                try:
                    crit = int(arg)
                except:
                    print('***crit value must be an integer***')

            elif opt in ('-t', '--time'):
                try:
                    time_window_minutes = int(arg)
                except:
                    print('***time window value must be an integer***')

            elif opt in ('-f', '--file'):
                try:
                    file_path = str(arg)
                except:
                    print('***file name value must be a string***')

            elif opt in ('-V', '--version'):
                print(Version)
                sys.exit(WARNING)
            else:
                print(usage)
                sys.exit(WARNING)
    except:
        sys.exit(CRITICAL)
    # confirm that warning level is less than critical level, alert and exit if check fails
    if warn > crit:
        print('***warning level must be less than critical level***')
        sys.exit(CRITICAL)
    return


# main function
def main():
    argv = sys.argv[1:]
    command_line_validate(argv)

    # Read the stats from /proc/stat - results are in cpu_percent[] and io_wait_percent[]
    get_cpu_stats()

    # Read results from previous time period (default 10 minutes)
    results = read_historical_results()

    # Get actual usage
    total_cpu = cpu_percent['cpu']
    results[timestamp] = total_cpu

    # Save current results (current measurement + data from past period)
    write_results_to_file(results)

    # Compute the average
    avg = sum(results.values()) / len(results)

    # Build the status message (service output message) and set the exit code
    exit_code, result_message = check_status(avg)

    print(result_message)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
