#!/usr/bin/python

import pickle
import numpy as np

import roslib
roslib.load_manifest('smach')
roslib.load_manifest('hrl_rfh_fall_2011')
import roslib.substitution_args
import rospy
import smach
from geometry_msgs.msg import Point 
from std_msgs.msg import Int8

class InputParser(smach.State):
    def __init__(self):
        smach.State.__init__(self, outcomes=['ell_up', 'ell_down', 'ell_left', 
                                             'ell_right', 'ell_in','ell_out',
                                             'shave','global_move'],
                                             input_keys=['goal_location'],
                                             output_keys=['goal_pose'])
       
        
        self.selection_out = rospy.Publisher('sm_selected_pose', Int8, latch=True)
        
        path = roslib.substitution_args.resolve_args('$(find hrl_rfh_fall_2011)/data/bilateral_poses.pkl')
        print path
        try: 
            f = file(path, 'r')
            self.pose_dict = pickle.load(f)
            self.keys = sorted(self.pose_dict.keys())
            print self.keys
            print self.pose_dict
            f.close()
            rospy.loginfo("Succesfully loaded pose dict")
        except:
            rospy.logwarn("Could Not Import Head-relative Poses! Global Move cannot succeed")


    def execute(self, userdata):
        if isinstance(userdata.goal_location, type(Int8())):
            userdata.goal_location.data
            if userdata.goal_location.data == -1: 
                print "Shave!"
                return 'shave'
            else:
                print "Global Move!"
                self.selection_out.publish(userdata.goal_location.data)
                userdata.goal_pose = self.pose_dict[self.keys[userdata.goal_location.data]]
                print 'GLOBAL MOVE GOAL: ', self.pose_dict[self.keys[userdata.goal_location.data]]
                return 'global_move'

        elif isinstance(userdata.goal_location, type(Point())): 
            print "GOAL LOCATION IN LOCAL INPUT PARSER: ", userdata.goal_location
            if userdata.goal_location.y == 1:
                return 'ell_up'
            elif userdata.goal_location.y == -1:
                return 'ell_down'
            elif userdata.goal_location.x == -1:
                return 'ell_left'
            elif userdata.goal_location.x == 1:
                return 'ell_right'
            elif userdata.goal_location.z == 1:
                return 'ell_out'
            elif userdata.goal_location.z == -1:
                return 'ell_in'
        else:
            print "Unrecognized data type"
#class LocalInputParser(smach.State):
#    def __init__(self):
#        smach.State.__init__(self, outcomes=['ell_up', 'ell_down', 'ell_left', 
#                                             'ell_right', 'ell_in','ell_out'],
#                                             input_keys=['goal_location'])
#        
#    def execute(self, userdata):
#        print "GOAL LOCATION IN LOCAL INPUT PARSER: ", userdata.goal_location
#        if userdata.goal_location.y == 1:
#            return 'ell_up'
#        elif userdata.goal_location.y == -1:
#            return 'ell_down'
#        elif userdata.goal_location.x == -1:
#            return 'ell_left'
#        elif userdata.goal_location.x == 1:
#            return 'ell_right'
#        elif userdata.goal_location.z == 1:
#            return 'ell_out'
#        elif userdata.goal_location.z == -1:
#            return 'ell_in'
#       
#class GlobalInputParser(smach.State):
#    def __init__(self):
#        smach.State.__init__(self, outcomes=['shave','move'],
#                                   input_keys=['goal_location'],
#                                   output_keys=['goal_pose'])
#        
#        self.selection_out = rospy.Publisher('sm_selected_pose', Int8, latch=True)
#
#        try: 
#            f = file('../../data/pickled_poses.pkl', 'r')
#            self.pose_dict = pickle.load(f)
#            f.close()
#        except:
#            rospy.logwarn("Could Not Import Head-relative Poses! Global Move cannot succeed")
#    
#    def execute(self, userdata):
#        if userdata.goal_location.data == -1: 
#            return 'shave'
#        else:
#            self.selection_out.publish(userdata.goal_location.data)
#            userdata.goal_pose = self.pose_dict[self.pose_dict.keys()[userdata.goal_location.data]]
#            return 'move' 

if __name__=='__main__':
    lip = LocalInputParser()
    gip = GlobalInputParser()

