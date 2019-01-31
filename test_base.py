'''
Created on Sep 10, 2018

@author: sboddu
'''


import os, sys, unittest, xmlrunner, re
import compileall
#from concurrencytest import ConcurrentTestSuite, fork_for_tests
from coverage import Coverage
import random
from distutils.util import strtobool
import shutil
import threading
import traceback
import django
import pymysql
from argparse import ArgumentParser

#Load the django settings similar to what manage.py does
pymysql.install_as_MySQLdb()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings.default")
django.setup()

MAX_PARALLEL_JOBS   = 16        # maximum number regardless of cpu
REPORTS_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "reports")
COVERAGE_DIR = os.path.join(REPORTS_DIR, "coverage")
TEST_REPORTS_DIR = os.path.join(REPORTS_DIR, "tests")
PYLINT_DIR = os.path.join(REPORTS_DIR, "pylint")
DOCS_DIR = os.path.join(REPORTS_DIR, "docs")
SPHINX_DOCS_DIR = os.path.join(DOCS_DIR, "sphinx")
SPHINX_SETUP_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "sphinx_docs_setup")
COVERAGE_EXCLUDE_RULES = ["*site-packages*", "*/test/*", "*edai/splunk/python*", "virtualenv/lib*"]
SRC_DIRS = ["install"]

# The following are the default paths to be waived in the log files before comparing between gold and logs. These paths would differ based on username, timestamps and versions.
# If these are not waived during the gold vs test log diff, these might
# pass at owner of the tests but will fail at others.
DEFAULT_PATH_WAIVERS = ''

class TestBase(unittest.TestCase):

    '''
    Top level test class for the ProjectInstaller project. This should be the parent class for any test class under this project.
    All unit and integration tests would be running using this test infrastructure class.
    '''

    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass 

    def setUp(self):

        self.regress_dir = None
        self.regress_basedir = os.path.abspath(
            '%s/../regression' %
            os.path.dirname(__file__))
        self.test_file_name = None
        self.gold_file_name = None
        self.diff_file_name = None

        # Setup all the log file paths
        self.set_regress_dir_paths()
        print("Test: %s is running under PID: %s of parent PID: %s"%(self.test_name, os.getpid(), os.getppid()))

        # test dir is common to all tests in a test class. When the tests are
        # running in parallel, sometime makedirs() may see conflicts. So lock
        # the operation and ignore the exceptions
        try:
            lock = threading.Lock()
            lock.acquire()
            if not os.path.isdir(self.get_test_dir()):
                print("Creating the test dir: %s" % self.get_test_dir())
                os.makedirs(self.get_test_dir(), 0o755)
        except Exception as exc:
            print(str(exc))
        finally:
            lock.release()

        # clean up the previous test logs and test dir if exists.
        try:
            if os.path.isfile(self.test_file_name):
                print(
                    "Cleaning up the previous test log: %s" %
                    self.test_file_name)
                os.remove(self.test_file_name)
        except Exception as exc:
            print(str(exc))

        # clean up the previous temp and test dir if exists.
        try:
            if os.path.isdir(self.get_temp_dir()):
                print(
                    "Cleaning up the previous temp dir: %s" %
                    self.get_temp_dir())
                shutil.rmtree(self.get_temp_dir())
            print("Creating the temp dir: %s" % self.get_temp_dir())
            os.makedirs(self.get_temp_dir(), 0o755)
        except Exception as exc:
            print(str(exc))

        # Start coverage metrics
        self.coverage_obj = Coverage(
            data_file="%s/coverage" %
            COVERAGE_DIR,
            branch=True,
            data_suffix=True,
            cover_pylib=False,
            omit=COVERAGE_EXCLUDE_RULES,
            concurrency=[
                "multiprocessing",
                "thread"])
        self.coverage_obj.start()

    def tearDown(self):
        if self.coverage_obj:
            self.coverage_obj.stop()
            self.coverage_obj.save()

    def get_regress_dir(self):
        return self.regress_dir

    def get_regress_basedir(self):
        return self.regress_basedir

    def get_gold_dir(self):
        return os.path.join(self.regress_dir, 'gold')

    def get_test_dir(self):
        return os.path.join(self.regress_dir, 'test')

    def get_temp_dir(self):
        return os.path.join(self.regress_dir, 'temp/%s' % self.get_test_name())

    def get_data_dir(self):
        return os.path.join(self.regress_dir, 'data')

    def get_test_name(self):
        return self.test_name

    def _extract_regression_test_dir(self, path):
        return path.replace("test_", "")

    def set_regress_dir_paths(self):
        '''
        Auto-determines regression dir name based on module name.  For example, if the test
        case is tests/<app>/test_<name>, then the test dir is regression/<app>/<name>
        '''

        path = self.__class__.__module__.split('.')[1:]
        path[-1] = self._extract_regression_test_dir(path[-1])
        path = ["regression"] + path
        self.regress_dir = os.path.abspath(
            '%s/../%s' %
            (os.path.dirname(__file__),
             os.path.join(
                *
                path)))

        self.test_name = self._testMethodName
        self.test_file_name = os.path.join(
            self.regress_dir, "test/%s.log" %
            self.test_name)
        self.gold_file_name = os.path.join(
            self.regress_dir, "gold/%s.log" %
            self.test_name)
        self.diff_file_name = os.path.join(
            self.regress_dir, "%s.diff.out" %
            self.test_name)

    def log(self, msg):
        with open(self.test_file_name, "a") as test_log:
            test_log.write(msg)

    def diff(self, test_file_name=None, waivers='', sort=False):
        test_file = self.test_file_name
        gold_file = self.gold_file_name
        file_name = os.path.basename(self.test_file_name)
        if test_file_name:
            if not os.path.isabs(test_file_name):
                file_name = test_file_name
                test_file = os.path.join(
                    self.regress_dir, "test/%s" %
                    file_name)
                gold_file = os.path.join(
                    self.regress_dir, "gold/%s" %
                    file_name)
            else:
                file_name = os.path.basename(test_file_name)
                test_file = test_file_name
                gold_file = os.path.join(
                    self.regress_dir, "gold/%s" %
                    file_name)
        temp_golddiff_log = os.path.join(
            self.regress_dir,
            "test/%s_gold_waived.log" %
            file_name)
        temp_testdiff_log = os.path.join(
            self.regress_dir,
            "test/%s_test_waived.log" %
            file_name)
        temp_goldsort_log = os.path.join(
            self.regress_dir,
            "test/%s_gold_sorted.log" %
            file_name)
        temp_testsort_log = os.path.join(
            self.regress_dir,
            "test/%s_test_sorted.log" %
            file_name)
        if waivers:
            if sort:
                cmd = "grep -Ev '%s' %s > %s; grep -Ev '%s' %s > %s; sort %s > %s; sort %s > %s; diff -bB %s %s > %s"\
                    % (waivers, test_file, temp_testdiff_log, waivers, gold_file, temp_golddiff_log,
                       temp_testdiff_log, temp_testsort_log, temp_golddiff_log, temp_goldsort_log,
                       temp_testsort_log, temp_goldsort_log, self.diff_file_name)
            else:
                cmd = "grep -Ev '%s' %s > %s; grep -Ev '%s' %s > %s; diff -bB %s %s > %s"\
                    % (waivers, test_file, temp_testdiff_log, waivers, gold_file, temp_golddiff_log,
                       temp_testdiff_log, temp_golddiff_log, self.diff_file_name)
        else:
            if sort:
                cmd = "sort %s > %s; sort %s > %s; diff -bB %s %s > %s" % (test_file, temp_testsort_log, gold_file, temp_goldsort_log,
                                                                           temp_testsort_log, temp_goldsort_log, self.diff_file_name)
            else:
                cmd = "diff -bB %s %s > %s" % (test_file,
                                               gold_file, self.diff_file_name)
        status, msg = utils.execute_shell(cmd)
        '''if os.path.isfile(temp_testdiff_log):
            os.remove(temp_testdiff_log)
        if os.path.isfile(temp_golddiff_log):
            os.remove(temp_golddiff_log)
        if os.path.isfile(temp_testsort_log):
            os.remove(temp_testsort_log)
        if os.path.isfile(temp_goldsort_log):
            os.remove(temp_goldsort_log)'''
        if status!=0:
            print("status is %s" %(status))
        if os.path.getsize(self.diff_file_name)>0:
            print("%s and %s are different" %(test_file,gold_file))
        return (
            status == 0 and os.path.isfile(
                self.diff_file_name) and os.path.getsize(
                self.diff_file_name) == 0)

def generate_coverage_reports(reports_dir=COVERAGE_DIR, report="all"):
    '''
    This task combines all the coverage data files generated during all the tests and generates the coverage reports.
    :param report: type of the coverage report to be generated. Options: text|html|xml. Defaults to 'html'
    :param reports_dir: directory under which all coverage files to be found and reports to be generated. Defaults to reports/coverage
    '''

    print("\nInitiating code coverage analysis ...")
    coverage_obj = Coverage(data_file="%s/coverage"%reports_dir)
    coverage_obj.combine()
    coverage_obj.save()

    if report == "all":
        with open("%s/coverage.txt"%reports_dir, "w") as cov_rep:
            coverage_obj.report(file=cov_rep, show_missing=True)
            print("Generated Code-Coverage text report at %s/coverage.txt\n" % reports_dir)
        coverage_obj.html_report(directory=reports_dir)
        print("Generated Code-Coverage HTML report at %s\n" % reports_dir)
        coverage_obj.xml_report(outfile='%s/coverage.xml'%reports_dir)
        print("Generated Code-Coverage XML report at %s/coverage.xml\n" % reports_dir)
    elif report == "text":
        with open("%s/coverage.txt"%reports_dir, "w") as cov_rep:
            coverage_obj.report(file=cov_rep, show_missing=True)
            print("Generated Code-Coverage text report at %s/coverage.txt\n" % reports_dir)
    elif report == "html":
        coverage_obj.html_report(directory=reports_dir)
        print("Generated Code-Coverage HTML report at %s\n" % reports_dir)
    elif report == "xml":
        coverage_obj.xml_report(outfile='%s/coverage.xml'%reports_dir)
        print("Generated Code-Coverage XML report at %s/coverage.xml\n" % reports_dir)

def compile(sources=SRC_DIRS):
    """compile all python files"""

    for source in sources:
        compileall.compile_dir(source, force=1, quiet=True)

def generate_pylint_reports(sources=SRC_DIRS):
    """ Runs PyLint tool on the python sources and generates the score cards """

    os.system("pylint -f parseable %s | tee %s/pylint.out"%(" ".join(sources), PYLINT_DIR))


def test(package_name="tests", test_regex="*", coverage=True, parallel=MAX_PARALLEL_JOBS):
    '''
    Runs the mentioned unit tests.
    Code coverage can be enabled or disabled using 'coverage=True/False' parameter. By default its True. 
    Parameter 'parallel' decides how many parallel tests to run.
    If not given 16 jobs/tests run in parallel. parallel=1 runs tests in sequential mode.
    '''


    if coverage:
        coverage_obj = Coverage(data_file="%s/coverage"%COVERAGE_DIR, branch=True,
                            source=SRC_DIRS, data_suffix=True, cover_pylib=False,
                            omit=COVERAGE_EXCLUDE_RULES, concurrency=["multiprocessing", "thread"])
        coverage_obj.start()

    sys.stderr.write("Running tests for %s modules\n"%("all" if test_regex == "*" else test_regex))
    
    # auto-discover all pre-decided sequential tests with nameing test_sequential_*.py
    #suite_sequential = unittest.defaultTestLoader.discover(package_name, pattern="test_sequential_%s.py"%test_regex, top_level_dir="tests")
    suite_sequential = unittest.defaultTestLoader.discover(package_name, pattern="test_sequential_%s.py"%test_regex)
    total_seq_tests  = suite_sequential.countTestCases()
    if total_seq_tests > 0:
        suite_sequential = unittest.TestSuite(suite_sequential)
        sys.stderr.write("Running %s sequential test cases\n" % total_seq_tests)
        result_sequential = unittest.TextTestRunner(verbosity=2).run(suite_sequential)

    # auto-discover all parallel test cases
    suite = unittest.defaultTestLoader.discover(package_name, pattern="test_%s.py"%test_regex)
    total_parallel_tests = suite.countTestCases()
    parallel = min(total_parallel_tests, parallel) # reduce based on number of test cases
    print("Parallel is %s\n" %(parallel))
    sys.stderr.write("Running %s test cases with %s parallel jobs at a time\n" % (total_parallel_tests, parallel))
    if parallel > 1:
        suite = unittest.TestSuite(suite)

    result = xmlrunner.XMLTestRunner(output=TEST_REPORTS_DIR).run(suite)
    print("Generated XML Test Reports at %s\n" %TEST_REPORTS_DIR)

    # The following coverage_obj covers the top level (package level) statements
    if coverage:
        coverage_obj.stop()
        coverage_obj.save()

    seq_error_tests = list()
    seq_failure_tests = list()
    par_error_tests = list()
    par_failure_tests = list()

    # Categorize all the failed and error tests
    if total_seq_tests > 0:
        if result_sequential:
            seq_error_tests.extend(result_sequential.errors)
            seq_failure_tests.extend(result_sequential.failures)

    if total_parallel_tests > 0:
        if result:
            par_error_tests.extend(result.errors)
            par_failure_tests.extend(result.failures)

    print('SUMMARY:')
    print("Total tests ran: %s, sequential tests: %s, parallel tests %s"%(total_parallel_tests + total_seq_tests, total_seq_tests, total_parallel_tests))
    print("Total tests failed: %s, sequential tests: %s, parallel tests %s"%(len(seq_failure_tests) + len(par_failure_tests), len(seq_failure_tests), len(par_failure_tests)))
    print( "Total tests with errors: %s, sequential tests: %s, parallel tests %s\n"%(len(seq_error_tests) + len(par_error_tests), len(seq_error_tests), len(par_error_tests)))

    if (len(seq_error_tests) + len(par_error_tests) > 0):
        print("Tests with errors:\n%s\n%s"%("\n".join([getattr(error[0], 'test_id') for error in seq_error_tests]), "\n".join([getattr(error[0], 'test_id') for error in par_error_tests])))
    if (len(seq_failure_tests) + len(par_failure_tests) > 0):
        print("Tests with failures:\n%s\n%s"%("\n".join([getattr(failure[0], 'test_id') for failure in seq_failure_tests]), "\n".join([getattr(failure[0], 'test_id') for failure in par_failure_tests])))

    #if len(seq_failure_tests) + len(par_failure_tests) + len(seq_error_tests) + len(par_error_tests) > 0:
    #    raise SystemExit("*** Regression tests failed ***")
 
def generate_python_docs(sources=SRC_DIRS):
    '''
    Generates the Pydoc based project documentation
    '''

    for source in sources:
        os.system("python -m pydoc %s/*.py > %s/%s.doc"%(source, DOCS_DIR, source))

def generate_sphinx_docs(sources=SRC_DIRS):
    '''
    Generates the Sphinx based project documentation
    '''

    for source in sources:
        os.system("sphinx-apidoc %s -o %s"%(source, SPHINX_SETUP_DIR))
    os.system("sphinx-build %s %s -b html"%(SPHINX_SETUP_DIR, SPHINX_DOCS_DIR))

if __name__ == "__main__":

    try:
        parser = ArgumentParser()
        parser.add_argument("-c", "--coverage", dest="coverage", action="store_true", default=False, help="When used, generates the cobertura code coverage files so that they can be used for reporting. [default: %(default)s]")
        parser.add_argument("-l", "--lint", dest="lint", action="store_true", default=False, help="When used, generates PyLint score files so that they can be used for reporting. [default: %(default)s]")
        parser.add_argument("-d", "--docs", dest="docs", action="store_true", default=False, help="When used, generates Python based and Sphinx based project documentation. [default: %(default)s]")
        parser.add_argument("-t", "--test", dest="test", action="store_true", default=False, help="When used, runs the default or requested unit tests. [default: %(default)s]")
        parser.add_argument("-p", "--parallel", dest="parallel", type=int, default=MAX_PARALLEL_JOBS, help="Number of parallel tests to run. [default: %(default)s]")
        parser.add_argument("-a", "--package", dest="package", default="tests", help="Package name for whcih the tests need to be run. Eg: tests, tests.install, tests.common, install, install.tests, qseed ... [default: %(default)s]")
        parser.add_argument("-r", "--case", dest="case", default="*", help="Single test module name or regex of one or more module names that to be unit tested. Eg: check* for test_check* tests ... [default: %(default)s]")

        # Process arguments
        args = parser.parse_args()

        # Clearup and recreate the reports directory for fresh run data
        if os.path.exists(REPORTS_DIR):
            shutil.rmtree(REPORTS_DIR)
        os.makedirs(REPORTS_DIR)
        os.makedirs(COVERAGE_DIR)
        os.makedirs(TEST_REPORTS_DIR)
        os.makedirs(PYLINT_DIR)
        os.makedirs(DOCS_DIR)
        os.makedirs(SPHINX_DOCS_DIR)

        if args.test:
            test(args.package, args.case, args.coverage, args.parallel)
        if args.coverage:
            generate_coverage_reports()
        if args.lint:
            generate_pylint_reports()
        if args.docs:
            generate_python_docs()
            generate_sphinx_docs()

    except Exception as exc:
        print(str(exc))
        print(traceback.format_exc())
        sys.exit(2)
