from tal.KeywordDrivenBase.Devices.Drivers import Factory
from tal.KeywordDrivenBase.Core.ConfigManager import PROJECT_PATH
import os
import shutil, psutil
import time, re
import configparser
from subprocess import Popen
import subprocess

DEBUG = False

class Esys:
    """
    Configuration example ('.._devices.cfg'):
    
      <TAL-DEVICE name='Esys' type='diagnostic'>
        <PARM name='PROJECT' value='G070_TSG__01__U012_040_040_042'/>
        <PARM name='VEHICLEINFO' value='G070_DIRECT'/>
        <PARM name='CONNECTION' value='bus'/>
        <PARM name='BUS_NAME' value='B3_CAN'/>
        <PARM name='INTERFACE' value='VECTOR_DIRECT'/>
        <PARM name='TAL' value='D:/DUST/Workspaces/BMW_35up_21_DCU/Utility/ESYS/SwFiles/TAL/TAL.xml'/>
        <PARM name='FA' value='D:/DUST/Workspaces/BMW_35up_21_DCU/Utility/ESYS/SwFiles/FA/FA.xml'/>
        <PARM name='VIN' value='BMWTEST111H123456'/>
        <PARM name='BTLD' value='00008FE2'/>      
        <PARM name='localdatasets' value='true'/>
        <PARM name='esysbatch' value='C:/EC-Apps/E-Sys/E-Sys.bat'/>
        <PARM name='logdir' value='Reports'/>
        <PARM name='configdir' value='Config/Devices/Esys'/>
        <PARM name='server_shell' value='True'/>
      </TAL-DEVICE>
    """
    def __init__ (self, config):
        self._isConnected = False
        self._isOpen = False
        self._isAuthenticated = False
        self._isImported = False
        self._checkConfigValid(config)
        self._config = config
        self._localDataSets = self._config.get('localdatasets', 'False').lower() == 'true'
        self._serverShell = self._config.get('server_shell', 'False').lower() == 'true'
        self._appPath = self._config['esysbatch']
        self._rootFolder = Factory.CheckFolderExists(f"{str(PROJECT_PATH)}/{self._config['configdir']}", reverse_slash=True)
        self._logFolder = Factory.CheckFolderExists(f"{str(PROJECT_PATH)}\\{self._config['logdir']}")
        self.LOG_PATH = self._logFolder + "\\EsysLog.log"
        self.configDir = f"{self._rootFolder}/config"
        self._masterCfg = f"{self.configDir}/master.config"
        self._fwlCfg = f"{self.configDir}/fwl.config"
        self._ncdCfg = f"{self.configDir}/ncd.config"
        self._talCfg = f"{self.configDir}/tal_ecu_ncd.config"
        self.SVT = Factory.CheckFolderExists(f"{self._rootFolder}/svt", reverse_slash=True)
        self.TAL = None
        self.TAL_PATH = Factory.CheckFolderExists(f"{self._rootFolder}/tal", reverse_slash=True)
        self.TAL_FILTER_PATH = f"{self._rootFolder}/tal/TAL_Filter.xml"  
        self.NCD_PATH = Factory.CheckFolderExists(f"{self._rootFolder}/ncd", reverse_slash=True)
        self.DATA_SETS_PATH_DEFAULT = Factory.CheckFolderExists(f"{self.NCD_PATH}/default/", reverse_slash=True)
        self.DATA_SETS_PATH = Factory.CheckFolderExists(f"{self.NCD_PATH}/datasets/", reverse_slash=True)
        self.VIN = None
        self.FA = Factory.CheckFolderExists(f"{self._rootFolder}/fa", reverse_slash=True)
        self.projectName = None
        self.BTLD = None
        self.NCD_SIGNED_PATH = Factory.CheckFolderExists(f"{self.NCD_PATH}/signed", reverse_slash=True)
        self.NCD_SIGNED_VIN_PATH = None
        self.NCD_UNSIGNED_PATH = Factory.CheckFolderExists(f"{self.NCD_PATH}/unsigned", reverse_slash=True)
        self.SVT_FILE_PATH = f"{self.SVT}/SVT.xml"
        self.FA_FILE_PATH = f"{self.FA}/FA.xml"
        self._checkFileExists(self.TAL_FILTER_PATH)
        self._dataSetsUpToDate = True
        self._serverProcess = None
        
    def _checkConfigValid(self, config):
        """
        method used to check if provided configuration is valid
        """
        if not type(config) == dict:
            raise Exception(f"ERROR: Invalid configuration file provided: {config}")
        # mandatory attributes:
        if not 'configdir' in config or \
           not 'logdir' in config or \
           not 'localdatasets' in config or \
           not 'esysbatch' in config:
            raise Exception(f"ERROR: Invalid configuration file provided: {config}")
    
    def SetConfig(self, config=None):
        """
        method use to set/change configuration
        config should be dict with device parameters
        """
        if config and type(config) == dict:
            self._config = config
        self._createMasterConfig()
    
    def Initialize(self):
        """
        method used to initialize all the files and configs
        """
        self.SetConfig()
        self._deployDefaultDataSets()
    
    def Open(self):
        """
        method that opens esys server
        """
        if self._isOpen: return self._isOpen

        cmd = f"cmd.exe /c start {self._appPath} -startserver"
        result, self._serverProcess = self._sendBatchCmd(cmd, end_process=False, shell=False)
        maxTimeoutCnt = 40
        cmd = f"{self._appPath} -server -check"
        while maxTimeoutCnt:
            result, log = self._sendBatchCmdAndGetLog(cmd)
            if result and not "Server is not running" in log:
                if DEBUG: print('Server is Online')
                self._isOpen = True
                break
            time.sleep(0.1)
            maxTimeoutCnt -= 1
        else:
            print('Server is Offline')
            self.Close()

        return self._isOpen
    
    def Connect(self):
        """
        method that creates the connection and reads the SVT and FA file from ECU and stores it
        """
        if self._isConnected: return self._isConnected

        cmd = f"{self._appPath} -server -openconnection {self._masterCfg}"
        result = self._sendBatchCmd(cmd)
        if DEBUG:
            connectionStatus = "connected" if result else "NOT connected"
            print(f'ECU is {connectionStatus}')
        if result: self._isConnected = True
        result &= self._createSVTFile()
        # result &= self._createFAFile()
        return result
    
    def Disconnect(self):
        """
        method that removes the connection to ecu
        """
        if not self._isConnected: return True
        
        result = self._sendBatchCmd(f"{self._appPath} -server -closeconnection")
        if result: self._isConnected = False
        return result
    
    def Close(self):
        """
        method that removes the connection to ecu and closes esys server
        """
        if not self._isOpen: return True
        self._isOpen = False
        result = self.Disconnect()
        result &= self._sendBatchCmd(f"{self._appPath} -server -stop")

        if self._serverProcess:
            try:
                print('Server is terminated.')
                self._serverProcess.kill()
            except:
                # if any error is during this procedure, ignore it.
                pass
            self._serverProcess = None
        self._killAllCmds()
        return result

    def _killAllCmds(self):
        for process in psutil.process_iter(attrs=['pid', 'name']):
            try:
                # Check if the process name is cmd.exe
                if 'cmd.exe' in process.info['name']:
                    # Terminate the process by its PID
                    os.system(f"taskkill /F /PID {process.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        # List all running processes using tasklist
        tasklistOutput = subprocess.check_output("tasklist", universal_newlines=True)
        
        # Search for cmd.exe processes
        for processName in tasklistOutput.split('\n'):
            if "cmd.exe" in processName:
                # Extract the PID and forcefully terminate the process
                try:
                    pid = int(processName.split()[1])
                    subprocess.call(["taskkill", "/F", "/PID", str(pid)], shell=True)
                except (IndexError, ValueError):
                    pass
        
        # the last option is to kill it on the os side.
        for process in psutil.process_iter(attrs=['pid', 'name']):
            try:
                import signal
                # Check if the process name is cmd.exe
                if 'cmd.exe' in process.info['name']:
                    os.kill(process.info['pid'], signal.CTRL_C_EVENT)
            except:
                pass
    
    def Authenticate(self):
        """
        method use to authenticate via swl certificate
        """
        if self._isAuthenticated: return self._isAuthenticated
        
        cmd = f"{self._appPath} -server -authenticationCoding -connection internet -useSwlSecCertificate"
        result = self._sendBatchCmd(cmd)
        if DEBUG:
            authStatus = "succeeded" if result else "NOT succeeded"
            print(f'ECU Authentication {authStatus}')
        if result: self._isAuthenticated = True
        return result
    
    def WriteCertificate(self, certificate, keypack, svt):
        """
        method use to authenticate via swl certificate
        Example of parameters definition:
        path ='C:\\Data\\CERT\\Keys'
        txt_path = 'D:/SWVersions/CertCyber/File.txt'
        svt_path = 'D:/SWVersions/CertCyber/SVT.xml'
        output_path = path + '\\Keys.xml'
        """
        result = True
        result &= self.Open()
        if not result:
            # do one retry in case of Server Offline
            result = self.Open()
        result &= self.Authenticate()
        result &= self.Connect()
        cmd = f"{self._appPath} -server -writeBindings -connection {self._masterCfg} -in {certificate} -secOCKeysPath {keypack} -svt {svt}"
        result = self._sendBatchCmd(cmd)
        if DEBUG:
            status = "succeeded" if result else "NOT succeeded"
            print(f'WritCertificate {status}')
        return result
    
    def _generateProjName(self, pdx_path: str, prefix: str = "NA05") -> str:
        # Extract filename without extension
        base_name = os.path.basename(pdx_path)
        file_name_no_ext = os.path.splitext(base_name)[0]
        
        # Replace dots with underscores
        cleaned_name = file_name_no_ext.replace('.', '_')
        
        # Prepend prefix
        project_name = f"{prefix}_{cleaned_name}"
        return project_name

    def ImportPdx(self, pdx_path):
        """
        method used to import another pdx in order to flash the ECU
        """
        projectName = self._generateProjName(pdx_path)
        if self._isImported: return self._isImported
        cmd = f"{self._appPath}   -pdximport {pdx_path} -project {projectName}"

        result = self._sendBatchCmd(cmd)
        if DEBUG:
            pdxStatus = "imported" if result else "NOT imported"
            print(f'Project PDX is {pdxStatus}')
        if result: self._isImported = True
        return result
        
    def FlashPdx(self, pdx_path=None, close_server=True):
        """
        method used to flash full pdx
        """
        result = True
        result &= self.Open()
        if not result:
            # do one retry in case of Server Offline
            result = self.Open()
        result &= self.Authenticate()
        result &= self.Connect()
        if pdx_path:
            result = self.ImportPdx(pdx_path)
            if not result: return result
        
        cmd = f"{self._appPath} -server -talexecution {self._masterCfg} -ignoreBATHAF"
        result = self._sendBatchCmd(cmd)
        if DEBUG:
            flashStatus = "completed" if result else "NOT completed"
            print(f'ECU flashing is {flashStatus}')
        if close_server:
            result &= self.Close()
        return result   
    
    def RestoreDataSets(self):
        """
        method used to read from ECU the current coding or to copy them from the 'NCD/default' folder
        """
        result = True
        if self._localDataSets:
            # copy from default to datasets folder
            self._copyDataSetsFromDefault()
        else:
            result &= self._readDataSetsFromECU()
        return result

    def UploadDataSets(self, check_modified=False):
        """
        method that flashes modified and signed NCD's and close the server
        @check_modified: check's if any SetParameter was called from last ecu upload
        """
        result = True
        if check_modified:
            if self._dataSetsUpToDate:
                return result
        result &= self.Open()
        if not result:
            # do one retry in case of Server Offline
            result &= self.Open()
        result &= self.Authenticate()
        result &= self.Connect()
        
        if not self._localDataSets:
            result &= self._readDataSetsFromECU()
        result &= self._convertDataSets()
        result &= self._signDataSets()
        
        talCfgPath = self._createTalEcuNcdConfig()
        cmd = f"{self._appPath} -server -talexecution {talCfgPath}"
        result &= self._sendBatchCmd(cmd)
        if DEBUG:
            dataStatus = "successfully" if result else "could NOT be"
            print(f"Data codings files {dataStatus} flashed to ECU")
        if result:
            self._dataSetsUpToDate = True
        return result   

    def GetParameter(self, name):
        """
        method used to read the parameter value from FWL file
        """
        data, value, parmData, fwlFile = self._getParameter(name)
        if DEBUG:
            print(f"Parameter '{name}' actual value:'{data} - {value}'")
        return value
    
    def SetParameter(self, name, value):
        """
        method used to update the FWL files. Will NOT write the data to ECU
        """
        parmData, parmValue, fwlContent, fwlFile = self._getParameter(name)

        dataToWrite = f"{name}:{parmData}[{str(value)}]\n"

        self._replaceParm(fwlContent, fwlFile, dataToWrite)
        if DEBUG:
            print(f"Parameter '{name}' set to value:'{parmData} - {str(value)}'")
        self._dataSetsUpToDate = False
        return True

    def _getParameter(self, name):
        # value, byte_start, length parameters to be added
        # go inside all FWL files, search for parameter name, modify value (if hex bytes, from byte to byte)
        if not self._localDataSets:
            self._readDataSetsFromECU()
        parmData = ""
        fwlList = self._getFilesAsList(self.DATA_SETS_PATH,".fwl", full_path = True)
        fwlFileName = None
        fwlContent = None
        foundParm = False
        if len(fwlList) == 0:
            raise Exception("ERROR: Esys: No *.fwl files detected in ../ncd/datasets/")
        for fwlFile in fwlList:
            with open(fwlFile, encoding="utf-8") as fwl:
                fwlContent = fwl.readlines()
                for line in fwlContent:
                    if name == line.strip().split(":")[0]:
                        parmData = line
                        fwlFileName = fwlFile
                        foundParm = True
                        break
            if foundParm:
                break
        # line format: AccRunningModeActivateSupress : SensData_G70 [255]
        parmDataList = parmData.strip().split(":")[1]
        data, value = parmDataList.split("[")
        return data, value[:-1], fwlContent, fwlFileName

    @staticmethod
    def _replaceParm(content, file_path, text, flags=0):
        """
        method used to replace line in fwl files with updated values (parameter value updates)
        """
        paramName = re.match(r'([^:]+):', text).group(1).strip()
        modified = False
    
        for i, line in enumerate(content):
            if re.match(f'^{re.escape(paramName)}:', line):
                content[i] = text
                modified = True
    
        if modified:
            with open(file_path, 'w', encoding="utf-8") as file:
                file.writelines(content)
    
    def _createFwlConfig(self):
        """
        method that creates the config in order to create NCD's from FWL files
        """
        path = self._fwlCfg
        self._checkFileExists(path)
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(path)

        config['CONFIG']['FA'] = self.FA
        config['CONFIG']['NCD_DIR'] = self.NCD_UNSIGNED_PATH
        config['CONFIG']['FWL_LIST'] = self._getFilesAsString(self.DATA_SETS_PATH)
        self._updateConfigFile(config, path)
        return path
    
    def _createMasterConfig(self):
        """
        method that creates the maser config
        """
        self._checkFileExists(self._masterCfg)
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(self._masterCfg)

        config['CONFIG']['PROJECT'] = self.projectName = self._config['project']
        config['CONFIG']['VEHICLEINFO'] = self._config['vehicleinfo']
        config['CONFIG']['CONNECTION'] = self._config['connection']
        if 'busname' in self._config:
            config['CONFIG']['BUS_NAME'] = self._config['busname']
        if 'interface' in self._config:
            config['CONFIG']['INTERFACE'] = self._config['interface']
        if 'url' in self._config:
            config['CONFIG']['URL'] = self._config['url']
        config['CONFIG']['TAL'] = self.TAL = self._config['tal']
        config['CONFIG']['FA'] = self.FA = self._config['fa']
        config['CONFIG']['VIN'] = self.VIN = self._config['vin']
        self.BTLD = self._config['btld']
        self._updateConfigFile(config, self._masterCfg)
        self.NCD_SIGNED_VIN_PATH = f"{self.NCD_SIGNED_PATH}/{self.VIN}"
    
    def _convertDataSets(self):
        """
        method that converts FWL files into usigned NCD's
        """
        fwlPath = self._createFwlConfig()    
        files = self._getFilesAsList(self.NCD_UNSIGNED_PATH, ".ncd", full_path = True)
        for file in files: os.remove(file)
        
        cmd = f"{self._appPath} -server -fwl2Ncd {fwlPath}"
        result = self._sendBatchCmd(cmd)
        
        if DEBUG:
            dataStatus = "successfully created" if result else "could NOT be created"
            print(f"Data codings (NCD unsigned) files {dataStatus} from FWL's")
        return result
    
    def _createNcdConfig(self):
        """
        method that creates the config in order to sign the NCD's
        """
        path = self._ncdCfg
        self._checkFileExists(path)
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(path)

        config['CONFIG']['FA'] = self.FA
        config['CONFIG']['VIN'] = self.VIN
        config['CONFIG']['SIGNED_NCD_DIR'] = self.NCD_SIGNED_PATH
        config['CONFIG']['NCD_LIST_1'] = self.BTLD + ';' + self._getFilesAsString(self.NCD_UNSIGNED_PATH)
        self._updateConfigFile(config, path)
        return path
    
    def _signDataSets(self):
        """
        method that sends unsigned NCD's to be signed
        """
        path = self._createNcdConfig()
        files = self._getFilesAsList(self.NCD_SIGNED_VIN_PATH, ".ncd", full_path = True)
        for file in files: os.remove(file)
        
        cmd = f"{self._appPath} -server -signNcd {path}"
        result = self._sendBatchCmd(cmd)
        
        if DEBUG:
            dataStatus = "successfully been signed" if result else "could NOT be signed"
            print(f"Data codings (NCD) files {dataStatus}")
        return result
    
    def _createTalEcuNcdConfig(self):
        """
        method that creates the config in order to flash the signed NCD's
        """
        path = self._talCfg
        self._checkFileExists(path)
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(path)
        config['CONFIG']['VIN'] = self.VIN
        config['CONFIG']['FA'] = self.FA
        config['CONFIG']['SVT'] = self.SVT_FILE_PATH
        config['CONFIG']['TAL'] = self.TAL
        config['CONFIG']['NCD_LIST'] = self._getFilesAsString(self.NCD_SIGNED_VIN_PATH)
        config['CONFIG']['TAL_FILTER'] = self.TAL_FILTER_PATH  
        self._updateConfigFile(config, path)
        return path
    
    def _createSVTFile(self):
        """
        method that cleans old SVT and reads the newest SVT file from ECU
        """
        # clean old files
        files = self._getFilesAsList(self.SVT, ".xml", full_path = True)
        for file in files: os.remove(file)
        
        cmd = f"{self._appPath} -server -readsvt -connection {self._masterCfg} -out {self.SVT_FILE_PATH}"
        result = self._sendBatchCmd(cmd)
        
        self._checkFileExists(self.SVT_FILE_PATH)
        if DEBUG:
            svtStatus = "created" if result else "could NOT be created"
            print(f'ECU SVT file {svtStatus}')
        return result
    
    def CreateCertRequestFile(self):
       
        result = True
        result &= self.Open()
        if not result:
            # do one retry in case of Server Offline
            result = self.Open()
 
        result &= self.Authenticate()
        result &= self.Connect()
 
        # cmd = f"{self._appPath} -server -writeBindings -connection {self._masterCfg} -in {certificate} -secOCKeysPath {keypack} -svt {svt}"
        cmd = f"{self._appPath} -server -generateCSR -connection {self._masterCfg} -out C:\Data\CERT\requestCBB.txt -vin BMWTEST111H123456" 
 
        # E-Sys.bat -generateCSR -connection C:\conf\connection.properties -out C:\Data\CERT\requestCBB[JSON].txt
        result = self.return_code(cmd=cmd, return_code=False)

        if DEBUG:
            status = "succeeded" if result else "NOT succeeded"
            print(f'ReadDataOK {status}')
        return result
    
    def _createFAFile(self):
        """
        method that cleans old FA and reads the newest FA file from ECU
        """
        # clean old files
        files = self._getFilesAsList(self.FA, ".xml", full_path = True)
        file_path = files[0]
        print(file_path)
        # Get the directory path
        directory_path = os.path.dirname(file_path) 
        # print(directory_path)     
        # os.remove(directory_path)
                
        cmd = f"{self._appPath} -server -readfa -connection {self._masterCfg} -out {self.FA_FILE_PATH}"
        result = self._sendBatchCmd(cmd)
        
        self._checkFileExists(self.FA_FILE_PATH)
        if DEBUG:
            svtStatus = "created" if result else "could NOT be created"
            print(f'ECU FA file {svtStatus}')
        return result
    
    def _readDataSetsFromECU(self):
        """
        method that reads data from ECU and stores NCD and FWL files in /NCD/datasets
        """
        self.Open()
        self.Connect()
        files = self._getFilesAsList(self.DATA_SETS_PATH, ".fwl", full_path = True)
        for file in files: os.remove(file)
        
        cmd = f"{self._appPath} -server -readNcd {self.SVT_FILE_PATH} -connection {self._masterCfg} -out {self.DATA_SETS_PATH} -notReadVin"
        result = self._sendBatchCmd(cmd)
        if not result:
            self.Close()
            raise Exception("ERROR: Failed to download data sets from ECU")
        if DEBUG:
            dataStatus = "created" if result else "could NOT be created"
            print(f'ECU dataset files (NCD and FWL) {dataStatus}')
        self.Close()
        return result

    def _deployDefaultDataSets(self):
        if not self._localDataSets:
            return
        self._copyDataSetsFromDefault()

    def _copyDataSetsFromDefault(self):
        """
        method that copy default fwls to datasets folder
        """
        # clear old fwls
        files = self._getFilesAsList(self.DATA_SETS_PATH, ".fwl", full_path = True)
        for file in files: os.remove(file)
        
        # copy default datasets
        files = self._getFilesAsList(self.DATA_SETS_PATH_DEFAULT, ".fwl")
        for file in files:
            shutil.copy(self.DATA_SETS_PATH_DEFAULT + file, self.DATA_SETS_PATH)
        if DEBUG:
            print("FWL files copied from 'NCD/default' into 'NCD/datasets' folder")       
    
    def _checkFileExists(self, path):
        """
        method used to check if specific file exists at a specific path
        """
        if not os.path.isfile(path):
            self.Close()
            raise Exception(f"ERROR: File not found: {path}")
    
    @staticmethod   
    def _getFilesAsList(path, suffix, full_path=False):
        """
        utility method that returns a list of files
        """
        files = []
        try:
            directory_path = os.path.dirname(path)
            for file in os.listdir(directory_path):
                if file.endswith(suffix):
                    name = file if not full_path else path + "/" + file
                    files.append(name)
        except FileNotFoundError:
            return ""
        return files

    @staticmethod 
    def _getFilesAsString(path):
        """
        method that returns a string of file paths separated by ;
        """
        files = ""
        filesAsList = os.listdir(path)
        fileNames = [item for item in filesAsList if not item.endswith('.md') and os.path.isfile(os.path.join(path, item))]
        
        for file in fileNames:
            files = files + ";" + path + "/" + file         
        return files[1:]

    def _updateConfigFile(self, config, path):
        """
        method that writes the content from a configparser obj into a file
        """
        if os.path.exists(path):
            with open(path, 'r+', encoding="utf-8") as cfg:
                cfg.truncate(0) #removes previous contents of the file
                config.write(cfg)
                cfg.readline(0)
        else:
            self.Close()
            raise Exception(f"ERROR: Couldn't find file to write config to {path}")

    def _sendBatchCmd(self, cmd, end_process=True, shell=True, return_code=True):
        """
        method used to send a command over e-sys batch file
        """
        result = True
        log = open(self.LOG_PATH, 'a+')
        if DEBUG:
            print (f"----->> {cmd}")

        process = Popen(cmd.split(" "), stdout=log, stdin=subprocess.PIPE, shell=shell)
        process.wait()
        log.flush()
        log.close()
        
        if not end_process:
            # return the process obj to kill it later
            return result, process
        if return_code:
            if process.returncode != 0: 
                result = False
        process.kill()
        return result

    def _sendBatchCmdAndGetLog(self, cmd):
        """
        method used to send a command over e-sys batch file
        """
        if DEBUG:
            print (f"----->> {cmd}")

        try:
            process = Popen(cmd.split(" "), shell=self._serverShell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            process.wait()
            stdout, stderr = process.communicate()
            process.kill()
            if process.returncode == 0:
                return True, stdout.strip()  # Return True for success and the output
            else:
                return False, stderr.strip()  # Return False for failure and the error message
        except Exception as e:
            process.kill()
            return False, stdout.strip()+str(e)  # Return False and the exception message if an error occurs
