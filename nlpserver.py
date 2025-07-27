#!/usr/bin/env python3

# Separately run nplserver is used by the nlpsolver.
#
# This server speeds up nlp parsing by setting up the stanza parser pipeline
# and taking urlencoded queries like
# http://localhost:8080/Barack%20Obama%20was%20born%20in%20Hawaii.
# answering them with the stanza parser results represented
# as a json structure
#
#-----------------------------------------------------------------
# Copyright 2022 Tanel Tammet (tanel.tammet@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#-------------------------------------------------------------------

# ======= imports =======

import sys
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import unquote

#martinodb imports
import nlpglobals
# Import nlpsolver for the solve_text function
import nlpsolver
#


try: 
  import stanza # the only non-standard library dependency
except:
  print("""nlpserver needs stanza: to install stanza, do
pip install stanza
python -c 'import stanza; stanza.download("en")'""")
  sys.exit(0)

# see https://stanfordnlp.github.io/stanza/
# to install stanza, do 
#  pip install stanza
#  python -c 'import stanza; stanza.download("en")'

# ======= configuration globals ======

# host_name="localhost"
# server_port=8080
# gk_path="./gk"
# logfile="/dev/null" # here server logs the requests
# axiomfiles=None # "wnet_10k.js cnet_50k.js quasi_50k.js" # set to None to read no axioms

#martinodb
host_name=nlpglobals.server_name
server_port=nlpglobals.server_port
gk_path=nlpglobals.prover_fname
logfile="/dev/null" # here server logs the requests

# axiomfiles=None # "wnet_10k.js cnet_50k.js quasi_50k.js" # set to None to read no axioms

#axiomfiles="wnet_10k.js cnet_50k.js quasi_50k.js"
# axiomfiles="wnet_10k.js cnet_50k.js quasi_50k.js martinodb_appendto_wnet.json"
axiomfiles="wnet_10k_mod_martinodb_v01.js cnet_50k.js quasi_50k.js"

# axiomfiles="wnet_10k.js"
# axiomfiles="cnet_50k.js"
# axiomfiles="quasi_50k.js"



# ====== command line parsing ======

def parse_cmd_line():
  debug_flag = False
  cmd_axiomfiles = None
  cmd_host_name = None
  cmd_server_port = None
  
  if len(sys.argv) < 2:
    return {"debug_flag": debug_flag, "cmd_axiomfiles": cmd_axiomfiles, "cmd_host_name": cmd_host_name, "cmd_server_port": cmd_server_port}
    
  params = sys.argv[1:]
  elpos = -1
  skippos = 0
  
  for el in params:
    elpos += 1
    if skippos > 0:
      skippos = skippos - 1
      continue
      
    if el in ["-debug", "--debug"]:
      debug_flag = True
    elif el in ["-axioms", "--axioms"]:
      axiom_files_list = []
      fpos = 1
      while elpos + fpos < len(params):
        if not params[elpos + fpos] or params[elpos + fpos].startswith("-"):
          break
        axiom_files_list.append(params[elpos + fpos])
        fpos += 1
      skippos = fpos - 1
      # Join the axiom files into a space-separated string as expected by the code
      cmd_axiomfiles = " ".join(axiom_files_list)
    elif el in ["-host_name", "--host_name"]:
      if elpos + 1 >= len(params):
        print("-host_name takes a hostname parameter")
        sys.exit(1)
      cmd_host_name = params[elpos + 1]
      skippos = 1
    elif el in ["-server_port", "--server_port"]:
      if elpos + 1 >= len(params):
        print("-server_port takes a port number parameter")
        sys.exit(1)
      try:
        cmd_server_port = int(params[elpos + 1])
      except ValueError:
        print("-server_port takes an integer port number parameter")
        sys.exit(1)
      if cmd_server_port < 1 or cmd_server_port > 65535:
        print("-server_port takes a valid port number (1-65535)")
        sys.exit(1)
      skippos = 1
    elif el in ["help", "-help", "--help"]:
      print_help()
      sys.exit(0)
    elif el and el[0] == "-":
      print(f"Error: Option {el} is not recognized.")
      print_help()
      sys.exit(1)
      
  return {"debug_flag": debug_flag, "cmd_axiomfiles": cmd_axiomfiles, "cmd_host_name": cmd_host_name, "cmd_server_port": cmd_server_port}

def print_help():
  helptext = """
nlpserver.py - NLP Server for nlpsolver

Usage: nlpserver.py [options]

Options:
  -axioms, --axioms <file1> <file2> ...   Specify axiom files to load
  -debug, --debug                         Enable debug mode
  -host_name, --host_name <hostname>      Specify server hostname (default: from nlpglobals)
  -server_port, --server_port <port>      Specify server port (default: from nlpglobals)
  -help, --help                           Show this help message

Examples:
  nlpserver.py -axioms wnet_10k.js cnet_50k.js quasi_50k.js
  nlpserver.py -debug -axioms wnet_10k.js
  nlpserver.py -host_name 0.0.0.0 -server_port 8080
"""
  print(helptext)


# ====== globals used during work ========

nlp=None # at startup nlp is assigned the stanza pipeline
debug_mode=False # global debug flag

count=0
import time

# === request processing ===

class MyServer(BaseHTTPRequestHandler):
  def do_GET(self):
    global debug_mode
    text = unquote(self.path)  # urldecode
    
    # Debug the exact path received
    if debug_mode:
      print(f"Received path: '{text}'")
    
    # Check if this is a solve request with the new prefix
    if text.startswith("/_s_/"):
      if debug_mode:
        print("Detected solve request")
      
      # Remove prefix
      text = text[5:]  
      
      # Extract options and text
      parts = text.split('/', 1)  # Split only on first slash
      
      if len(parts) == 2:
        options_str, query_text = parts
        
        # Parse options
        if options_str.lower() != "null":
          try:
            options = json.loads(options_str)
          except:
            options = None
        else:
            options = None
            
        if debug_mode:
          print(f"Processing text for solving with options: '{options}'")
        result = solve_text(query_text, options)
      else:
        # Backward compatibility - no options provided
        if debug_mode:
          print(f"Processing text for solving (no options): '{text}'")
        result = solve_text(text)
        
    else:
      # Regular parse request
      if debug_mode:
        print(f"Detected parse request: '{text}'")
      if text:
        text = text[1:]  # remove initial slash
      if debug_mode:
        print(f"Processing text for parsing: '{text}'")
      result = parse_text(text)  # call stanza parser
    
    self.send_response(200)
    self.send_header("Content-type", "text/json")
    self.end_headers()    
    self.wfile.write(bytes("%s\n" % result, "utf-8"))


def parse_text(text):
  global nlp, debug_mode
  #global count
  #print("start parse_text count",count)
  doc=nlp(text)
  #
  if debug_mode:
    print("doc=nlp(text):\n", doc)
    try:
      print("Number of elements in doc:", len(doc.sentences))
    except Exception as e:
      print(f"Error when getting number of elements in doc: {e}")
  #
  docpy = doc.to_dict()
  #
  if debug_mode:
    print("docpy:\n", docpy)
  #
  entities=[]
  for el in doc.entities:
    entities.append(el.to_dict())
  wrapper={"doc": docpy, "entities": entities}    
  resjson=json.dumps(wrapper)
  #print("end parse_text count",count)
  #count+=1
  return resjson

def solve_text(text, options=None):
  """Call the answer_question function from nlpsolver to solve a question."""
  try:
    # Call the answer_question function from nlpsolver with options
    answer = nlpsolver.answer_question(text, options)
    # Return the answer as JSON
    return json.dumps({"answer": answer})
  except Exception as e:
    return json.dumps({"error": "Error processing request", "details": str(e)})

# ====== starting ======

if __name__ == "__main__":   
  # Parse command-line arguments
  cmd_options = parse_cmd_line()
  debug_flag = cmd_options["debug_flag"]
  debug_mode = debug_flag  # Set global debug flag
  
  # Override axiomfiles if provided via command line
  if cmd_options["cmd_axiomfiles"] is not None:
    axiomfiles = cmd_options["cmd_axiomfiles"]
  
  # Override host_name if provided via command line
  if cmd_options["cmd_host_name"] is not None:
    host_name = cmd_options["cmd_host_name"]
  
  # Override server_port if provided via command line
  if cmd_options["cmd_server_port"] is not None:
    server_port = cmd_options["cmd_server_port"]
  
  if debug_flag:
    print(f"Debug mode enabled. Using axiomfiles: {axiomfiles}")
    print(f"Server will start on {host_name}:{server_port}")
  
  print("Starting to build the stanza pipeline.")     
  # no download_method for stanza 1.3
  # nlp = stanza.Pipeline(lang='en', processors='tokenize,ner,pos,lemma,depparse', download_method=stanza.DownloadMethod.REUSE_RESOURCES)
  # next one is for stanza 1.4
  nlp = stanza.Pipeline(lang='en', processors='tokenize,ner,pos,lemma,depparse', download_method=stanza.DownloadMethod.REUSE_RESOURCES)
  #webServer = HTTPServer((host_name, server_port), MyServer)  # does not do parallel requests
  webServer = ThreadingHTTPServer((host_name, server_port), MyServer) # requests run in parallel
  print("Server started http://%s:%s" % (host_name, server_port))
  try:
    print("Starting to read gk solver shared memory database.")
    gkcommand=gk_path+" "+"dummy.js -readkb -defaults -relatedwords -similarities -mbsize 3000"
    #gkcommand=gk_path+" "+"dummy.js -readkb -defaults -relatedwords -similarities -mbsize 3000 cnet_50k.js quasi_50k.js wnet_10k.js"
    #gkcommand=gk_path+" "+"wnet_10k.js -readkb -defaults -relatedwords -similarities -mbsize 3000 "
    if axiomfiles:
      gkcommand=gk_path+" "+axiomfiles+" -readkb -defaults -relatedwords -mbsize 3000"
      print("Reading axiom files "+axiomfiles+".")
    else:
      gkcommand=gk_path+" "+"dummy.js -readkb -defaults -relatedwords -similarities -mbsize 3000"  
      print("No axiomfiles are read.")
    os.system(gkcommand)
    print("gk solver shared memory database ready.")   
  except:
    print("Could not read gk solver shared memory database.")
  print("Server ready.")
  try:
      buffer = 1
      sys.stderr = open(logfile, 'w', buffer)
      webServer.serve_forever()     
  except KeyboardInterrupt:
      pass

  webServer.server_close()
  print("Server stopped.")

# ===== the end ======